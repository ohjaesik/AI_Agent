# app/api/main.py
"""FastAPI 기반 AX Delivery Planner API 서버.

CLI와 같은 core workflow를 HTTP로 노출한다. UI/외부 시스템은 이 API를 통해
회사 bootstrap, 문서 업로드/색인, RAG 검색, 분석 실행, Human Review 적용,
인증 토큰 발급을 수행할 수 있다.

주의:
- 실제 분석 실행은 `app.main.run_demo`를 재사용하므로 CLI와 API의 workflow 동작이 같다.
- `/analysis/run` 응답에는 최근 model decision, Supervisor delegation, autonomy loop
  decision을 함께 넣어 UI에서 Agent 동작을 확인할 수 있게 한다.
- 문서 재색인은 admin role만 허용한다.
- dashboard summary, analysis response, 내장 테스트 HTML은 별도 모듈로 분리해
  route 함수가 orchestration만 담당하게 한다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.api.dashboard import build_dashboard_summary
from app.api.responses import build_analysis_response
from app.api.security import create_access_token, require_api_key, validate_api_key
from app.api.test_ui import TEST_UI_HTML
from app.auth.users import authenticate_user, create_user
from app.company_bootstrap.runner import run_bootstrap_supervisor_graph
from app.db.database import SessionLocal
from app.ingestion.service import ingest_file
from app.main import DEFAULT_STATE_OUTPUT_PATH, run_demo
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

# Mount outputs folder to serve generated docx files for download
OUTPUTS_DIR = Path("outputs")
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")


class CompanyBootstrapRequest(BaseModel):
    """회사 bootstrap API 요청 스키마."""

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
    """Human Review 결과를 ranking에 반영하기 위한 요청 스키마."""

    priority_ranking: dict[str, Any]
    human_review: dict[str, Any]


class TokenRequest(BaseModel):
    """테스트/로컬 API 인증 토큰 발급 요청."""

    user_id: str = "api-user"
    role: str = "analyst"
    expires_minutes: int | None = None


class RegisterRequest(BaseModel):
    """로컬 사용자 등록 요청."""

    username: str
    password: str
    role: str = "analyst"


class LoginRequest(BaseModel):
    """로컬 사용자 로그인 요청."""

    username: str
    password: str
    expires_minutes: int | None = None


@app.get("/health")
def health() -> dict[str, str]:
    """서버 생존 확인 endpoint."""

    return {"status": "ok"}


@app.get("/dashboard/summary")
def dashboard_summary(
    company_id: int | None = None,
    project_id: int | None = None,
    access: AccessContext = Depends(require_api_key),
) -> dict[str, Any]:
    """프론트 홈 대시보드가 표시할 실제 DB/최근 실행 요약을 반환한다.

    이 endpoint는 화면에 demo/mock 숫자를 만들지 않는다. 회사/프로젝트/업무/문서/chunk
    수는 DB에서 직접 읽고, 최근 분석 후보·모델 결정·비용은 workflow_state JSON이 있을
    때만 보여준다.
    """

    try:
        with SessionLocal() as db:
            return build_dashboard_summary(db=db, access=access, company_id=company_id, project_id=project_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Dashboard summary failed: {type(exc).__name__}: {exc}") from exc


@app.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics() -> str:
    """Prometheus scrape용 metrics endpoint."""

    return metrics.render_prometheus()


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    """백엔드 단독 smoke-test HTML을 반환한다."""
    return TEST_UI_HTML


@app.get("/ui", response_class=HTMLResponse)
def ui() -> str:
    """백엔드 단독 smoke-test HTML을 `/ui` 경로에서도 제공한다."""
    return TEST_UI_HTML


@app.post("/auth/token")
def issue_token(request: TokenRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
    """X-API-Key를 검증한 뒤 로컬 JWT access token을 발급한다."""

    validate_api_key(x_api_key)
    token = create_access_token(user_id=request.user_id, role=request.role, expires_minutes=request.expires_minutes)
    return {"access_token": token, "token_type": "bearer", "role": request.role, "user_id": request.user_id}


@app.post("/auth/register")
def register_user(request: RegisterRequest, access: AccessContext = Depends(require_api_key)) -> dict[str, Any]:
    """admin 권한으로 로컬 사용자 계정을 만든다."""

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
    """username/password를 검증해 JWT를 발급한다."""

    try:
        with SessionLocal() as db:
            user = authenticate_user(db=db, username=request.username, password=request.password)
        token = create_access_token(user_id=user.username, role=user.role, expires_minutes=request.expires_minutes)
        return {"access_token": token, "token_type": "bearer", "role": user.role, "user_id": user.username}
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Login failed: {type(exc).__name__}: {exc}") from exc


@app.post("/companies/bootstrap")
def bootstrap_company_endpoint(request: CompanyBootstrapRequest, access: AccessContext = Depends(require_api_key)) -> dict[str, Any]:
    """회사 공식자료 수집, 문서 저장, 후보 업무 discovery를 실행한다."""

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
    """업로드 문서를 저장하고 필요하면 즉시 RAG 색인한다.

    업로드 파일은 임시 파일로 저장한 뒤 ingestion service에 넘긴다. service가
    원본 저장소와 DB metadata, chunk 색인을 처리한다.
    """

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
    """단일 query로 RAG 검색 결과를 확인한다."""

    try:
        with SessionLocal() as db:
            results = search_similar_chunks(db=db, query=query, company_id=company_id, process_id=process_id, top_k=top_k, user_role=access.role)
        return {"status": "ok", "query": query, "company_id": company_id, "process_id": process_id, "user_role": access.role, "count": len(results), "results": results}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"RAG search failed: {type(exc).__name__}: {exc}") from exc


@app.post("/rag/reindex")
def reindex_rag(
    company_id: int | None = None,
    reset: bool = True,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
    chunk_strategy: str | None = None,
    semantic_similarity_threshold: float | None = None,
    semantic_min_chunk_chars: int | None = None,
    batch_size: int = 64,
    access: AccessContext = Depends(require_api_key),
) -> dict[str, Any]:
    """회사 문서를 다시 chunking/embedding 색인한다.

    semantic chunking 파라미터를 API에서도 넘길 수 있게 해, 운영 중 chunk 전략을
    바꾸고 즉시 재색인할 수 있다. DB 전체에 영향을 줄 수 있으므로 admin만 허용한다.
    """

    if access.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin role can reindex RAG documents.")
    try:
        inserted_count = index_documents(
            company_id=company_id,
            reset=reset,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            batch_size=batch_size,
            chunk_strategy=chunk_strategy,
            semantic_similarity_threshold=semantic_similarity_threshold,
            semantic_min_chunk_chars=semantic_min_chunk_chars,
        )
        return {"status": "ok", "inserted_chunks": inserted_count, "chunk_strategy": chunk_strategy}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Reindex failed: {type(exc).__name__}: {exc}") from exc


@app.post("/analysis/run")
def run_analysis(
    project_id: int | None = None,
    company_id: int | None = None,
    auto_approve: bool = True,
    thread_id: str = "ax-planner-api",
    allow_agent_extra_loop: bool | None = None,
    supervisor_goal: str | None = None,
    access: AccessContext = Depends(require_api_key),
) -> dict[str, Any]:
    """AX 분석 workflow를 API에서 실행한다.

    CLI의 `run_demo`를 그대로 호출하므로 Supervisor LLM, 모델 라우팅, 자율 loop,
    Human Review interrupt 동작이 CLI와 같다. 응답에는 UI에서 바로 보여주기 좋은
    최근 trace만 잘라 담고, 전체 state는 CLI 실행의 workflow_state 파일에서 확인한다.
    """

    try:
        result = run_demo(
            project_id=project_id,
            company_id=company_id,
            thread_id=thread_id,
            auto_approve=auto_approve,
            verbose=False,
            state_output_path=DEFAULT_STATE_OUTPUT_PATH,
            allow_agent_extra_loop=allow_agent_extra_loop,
            supervisor_goal=supervisor_goal,
        )
        return build_analysis_response(result=result, access=access)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Analysis failed: {type(exc).__name__}: {exc}") from exc


@app.post("/reviews/apply-ranking")
def apply_review_to_ranking(request: ReviewApplyRequest, access: AccessContext = Depends(require_api_key)) -> dict[str, Any]:
    """Human Review 결정으로 우선순위 payload를 수정한다."""
    if access.role not in {"manager", "admin"}:
        raise HTTPException(status_code=403, detail="Only manager/admin role can apply human review decisions.")
    result = apply_human_review_to_ranking(priority_ranking=request.priority_ranking, human_review=request.human_review)
    return {"status": "ok", "priority_ranking": result}
