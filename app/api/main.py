# app/api/main.py

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from fastapi.middleware.cors import CORSMiddleware
from app.api.security import create_access_token, require_api_key, validate_api_key
from app.auth.users import authenticate_user, create_user
from app.company_bootstrap.runner import run_bootstrap_supervisor_graph
from app.db.database import SessionLocal
from app.ingestion.service import ingest_file
from app.main import run_demo
from app.monitoring.metrics import RequestMetricsMiddleware, metrics
from app.rag.indexer import index_documents
from app.rag.retriever import search_similar_chunks
from app.security.access_control import AccessContext
from app.tools.review_applier import apply_human_review_to_ranking

app = FastAPI(title="AX Delivery Planner API", version="0.1.0")
app.add_middleware(RequestMetricsMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow cross-origin requests for local frontend integration
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CompanyBootstrapRequest(BaseModel):
    company_name: str
    official_urls: list[str] = Field(default_factory=list)
    dart_api_key: str | None = None
    corp_code: str | None = None
    stock_code: str | None = None
    create_project: bool = True
    index: bool = True
    reset_company_chunks: bool = False
    thread_id: str = "bootstrap-supervisor-api"


class ReviewApplyRequest(BaseModel):
    priority_ranking: dict[str, Any]
    human_review: dict[str, Any]


class TokenRequest(BaseModel):
    user_id: str = "api-user"
    role: str = "analyst"
    expires_minutes: int | None = None


class RegisterRequest(BaseModel):
    username: str
    password: str
    role: str = "analyst"


class LoginRequest(BaseModel):
    username: str
    password: str
    expires_minutes: int | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics() -> str:
    return metrics.render_prometheus()


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return TEST_UI_HTML


@app.get("/ui", response_class=HTMLResponse)
def ui() -> str:
    return TEST_UI_HTML


@app.post("/auth/token")
def issue_token(request: TokenRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
    validate_api_key(x_api_key)
    token = create_access_token(user_id=request.user_id, role=request.role, expires_minutes=request.expires_minutes)
    return {"access_token": token, "token_type": "bearer", "role": request.role, "user_id": request.user_id}


@app.post("/auth/register")
def register_user(request: RegisterRequest, access: AccessContext = Depends(require_api_key)) -> dict[str, Any]:
    if access.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin role can create local users.")
    try:
        with SessionLocal() as db:
            user = create_user(db=db, username=request.username, password=request.password, role=request.role)
        return {"status": "ok", "user": {"id": user.id, "username": user.username, "role": user.role, "is_active": user.is_active}}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"User registration failed: {type(exc).__name__}: {exc}") from exc


@app.post("/auth/login")
def login_user(request: LoginRequest) -> dict[str, Any]:
    try:
        with SessionLocal() as db:
            user = authenticate_user(db=db, username=request.username, password=request.password)
        token = create_access_token(user_id=user.username, role=user.role, expires_minutes=request.expires_minutes)
        return {"access_token": token, "token_type": "bearer", "role": user.role, "user_id": user.username}
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Login failed: {type(exc).__name__}: {exc}") from exc


@app.post("/companies/bootstrap")
def bootstrap_company_endpoint(request: CompanyBootstrapRequest, access: AccessContext = Depends(require_api_key)) -> dict[str, Any]:
    try:
        result = run_bootstrap_supervisor_graph(
            company_name=request.company_name,
            official_urls=request.official_urls,
            dart_api_key=request.dart_api_key,
            corp_code=request.corp_code,
            stock_code=request.stock_code,
            create_project=request.create_project,
            index=request.index,
            reset_company_chunks=request.reset_company_chunks,
            thread_id=request.thread_id,
        )
        return {"status": "ok", "access": {"user_id": access.user_id, "role": access.role}, "result": result.to_dict()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Company bootstrap failed: {type(exc).__name__}: {exc}") from exc


@app.post("/documents/ingest")
def ingest_document(
    access: AccessContext = Depends(require_api_key),
    company_id: int = Form(...),
    file: UploadFile = File(...),
    process_id: int | None = Form(None),
    title: str | None = Form(None),
    document_type: str | None = Form(None),
    department: str | None = Form(None),
    security_level: str = Form("internal"),
    allowed_roles: str | None = Form(None),
    index: bool = Form(True),
) -> dict[str, Any]:
    suffix = Path(file.filename or "uploaded.txt").suffix or ".txt"
    temp_path: Path | None = None
    parsed_allowed_roles = [item.strip() for item in allowed_roles.split(",") if item.strip()] if allowed_roles else None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(file.file.read())

        with SessionLocal() as db:
            result = ingest_file(
                db=db,
                file_path=temp_path,
                company_id=company_id,
                process_id=process_id,
                title=title or Path(file.filename or temp_path.name).stem,
                document_type=document_type,
                department=department,
                security_level=security_level,
                allowed_roles=parsed_allowed_roles,
                uploaded_by_user_id=access.user_id,
                index=index,
            )

        return {"status": "ok", "access": {"user_id": access.user_id, "role": access.role}, "result": result.to_dict()}

    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Ingestion failed: {type(exc).__name__}: {exc}") from exc

    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass


@app.get("/rag/search")
def rag_search(query: str, company_id: int, process_id: int | None = None, top_k: int = 5, access: AccessContext = Depends(require_api_key)) -> dict[str, Any]:
    try:
        with SessionLocal() as db:
            results = search_similar_chunks(db=db, query=query, company_id=company_id, process_id=process_id, top_k=top_k, user_role=access.role)
        return {"status": "ok", "query": query, "company_id": company_id, "process_id": process_id, "user_role": access.role, "count": len(results), "results": results}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"RAG search failed: {type(exc).__name__}: {exc}") from exc


@app.post("/rag/reindex")
def reindex_rag(company_id: int | None = None, reset: bool = True, chunk_size: int = 800, chunk_overlap: int = 120, batch_size: int = 64, access: AccessContext = Depends(require_api_key)) -> dict[str, Any]:
    if access.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin role can reindex RAG documents.")
    try:
        inserted_count = index_documents(company_id=company_id, reset=reset, chunk_size=chunk_size, chunk_overlap=chunk_overlap, batch_size=batch_size)
        return {"status": "ok", "inserted_chunks": inserted_count}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Reindex failed: {type(exc).__name__}: {exc}") from exc


@app.post("/analysis/run")
def run_analysis(project_id: int | None = None, company_id: int | None = None, auto_approve: bool = True, thread_id: str = "ax-planner-api", access: AccessContext = Depends(require_api_key)) -> dict[str, Any]:
    try:
        result = run_demo(project_id=project_id, company_id=company_id, thread_id=thread_id, auto_approve=auto_approve, verbose=False)
        if "__interrupt__" in result:
            return {"status": "interrupted", "interrupt": str(result.get("__interrupt__"))}
        return {
            "status": "ok",
            "access": {"user_id": access.user_id, "role": access.role},
            "report_docx_path": result.get("report_docx_path"),
            "generation": result.get("report_data", {}).get("generation", {}),
            "citation_validation": result.get("report_data", {}).get("citation_validation", {}),
            "top_candidates": result.get("priority_ranking", {}).get("items", [])[:5],
            "compliance_summary": result.get("compliance_assessment", {}).get("summary", {}),
            "errors": result.get("errors", []),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Analysis failed: {type(exc).__name__}: {exc}") from exc


@app.post("/reviews/apply-ranking")
def apply_review_to_ranking(request: ReviewApplyRequest, access: AccessContext = Depends(require_api_key)) -> dict[str, Any]:
    if access.role not in {"manager", "admin"}:
        raise HTTPException(status_code=403, detail="Only manager/admin role can apply human review decisions.")
    result = apply_human_review_to_ranking(priority_ranking=request.priority_ranking, human_review=request.human_review)
    return {"status": "ok", "priority_ranking": result}


TEST_UI_HTML = """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <title>AX Delivery Planner Test UI</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 40px; max-width: 920px; }
    section { border: 1px solid #ddd; padding: 20px; margin-bottom: 20px; border-radius: 10px; }
    label { display:block; margin: 8px 0 4px; font-weight: 600; }
    input, button { padding: 8px; margin-bottom: 8px; }
    button { cursor: pointer; }
    pre { background:#111; color:#eee; padding:16px; overflow:auto; min-height:120px; }
  </style>
</head>
<body>
  <h1>AX Delivery Planner Test UI</h1>
  <section>
    <h2>0. Local API Key</h2>
    <label>APP_API_KEY(optional)</label>
    <input id="apiKey" type="password" placeholder="local-test-key" style="width: 300px" />
    <label>User Role</label>
    <input id="userRole" type="text" value="admin" style="width: 120px" />
    <button onclick="saveApiKey()">Save</button>
  </section>
  <section>
    <h2>1. 회사명 기반 DB 생성</h2>
    <label>Company Name</label>
    <input id="bootstrapCompanyName" type="text" value="삼성전자" style="width: 300px" />
    <label>Official URL</label>
    <input id="officialUrl" type="text" placeholder="https://..." style="width: 640px" />
    <button onclick="bootstrapCompany()">Bootstrap Company</button>
  </section>
  <section>
    <h2>2. 문서 업로드 + RAG 색인</h2>
    <label>Company ID</label>
    <input id="companyId" type="number" value="1" />
    <label>Process ID(optional)</label>
    <input id="processId" type="number" placeholder="optional" />
    <label>File</label>
    <input id="file" type="file" />
    <button onclick="ingest()">Upload & Index</button>
  </section>
  <section>
    <h2>3. RAG 검색 확인</h2>
    <label>Query</label>
    <input id="ragQuery" type="text" value="SOP 검색 작업표준서" style="width: 420px" />
    <button onclick="ragSearch()">Search RAG</button>
  </section>
  <section>
    <h2>4. 분석 실행</h2>
    <label>Project ID(optional)</label>
    <input id="projectId" type="number" placeholder="optional" />
    <label>Company ID(optional)</label>
    <input id="analysisCompanyId" type="number" placeholder="optional" />
    <button onclick="runAnalysis()">Run Analysis</button>
  </section>
  <pre id="output">ready</pre>
<script>
function saveApiKey() {
  localStorage.setItem('AX_APP_API_KEY', document.getElementById('apiKey').value || '');
  localStorage.setItem('AX_USER_ROLE', document.getElementById('userRole').value || 'analyst');
  document.getElementById('output').textContent = 'saved';
}
async function show(promise) {
  const out = document.getElementById('output');
  out.textContent = 'loading...';
  try { const res = await promise; const data = await res.json(); out.textContent = JSON.stringify(data, null, 2); }
  catch (e) { out.textContent = String(e); }
}
function authHeaders(json=true) {
  const key = localStorage.getItem('AX_APP_API_KEY') || '';
  const role = localStorage.getItem('AX_USER_ROLE') || 'analyst';
  const headers = json ? {'Content-Type':'application/json'} : {};
  if (key) headers['X-API-Key'] = key;
  if (role) headers['X-User-Role'] = role;
  return headers;
}
function bootstrapCompany() {
  const companyName = document.getElementById('bootstrapCompanyName').value;
  const officialUrl = document.getElementById('officialUrl').value;
  show(fetch('/companies/bootstrap', {method: 'POST', headers: authHeaders(), body: JSON.stringify({company_name: companyName, official_urls: officialUrl ? [officialUrl] : [], create_project: true, index: true, thread_id: 'bootstrap-supervisor-ui'})}));
}
function ingest() {
  const fd = new FormData();
  fd.append('company_id', document.getElementById('companyId').value);
  const processId = document.getElementById('processId').value;
  if (processId) fd.append('process_id', processId);
  fd.append('file', document.getElementById('file').files[0]);
  show(fetch('/documents/ingest', {method:'POST', headers: authHeaders(false), body: fd}));
}
function ragSearch() {
  const q = encodeURIComponent(document.getElementById('ragQuery').value);
  const companyId = document.getElementById('companyId').value;
  show(fetch(`/rag/search?query=${q}&company_id=${companyId}`, {headers: authHeaders(false)}));
}
function runAnalysis() {
  const projectId = document.getElementById('projectId').value;
  const companyId = document.getElementById('analysisCompanyId').value;
  const params = new URLSearchParams({auto_approve: 'true'});
  if (projectId) params.append('project_id', projectId);
  if (companyId) params.append('company_id', companyId);
  show(fetch(`/analysis/run?${params.toString()}`, {method:'POST', headers: authHeaders(false)}));
}
</script>
</body>
</html>
"""
