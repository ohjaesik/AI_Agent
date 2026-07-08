# app/api/main.py

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.db.database import SessionLocal
from app.ingestion.service import ingest_file
from app.main import run_demo
from app.rag.indexer import index_documents
from app.tools.review_applier import apply_human_review_to_ranking

app = FastAPI(title="AX Delivery Planner API", version="0.1.0")


class ReviewApplyRequest(BaseModel):
    priority_ranking: dict[str, Any]
    human_review: dict[str, Any]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return TEST_UI_HTML


@app.get("/ui", response_class=HTMLResponse)
def ui() -> str:
    return TEST_UI_HTML


@app.post("/documents/ingest")
def ingest_document(
    company_id: int = Form(...),
    file: UploadFile = File(...),
    process_id: int | None = Form(None),
    title: str | None = Form(None),
    document_type: str | None = Form(None),
    department: str | None = Form(None),
    security_level: str = Form("internal"),
    index: bool = Form(True),
) -> dict[str, Any]:
    suffix = Path(file.filename or "uploaded.txt").suffix or ".txt"

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
                index=index,
            )

        return {"status": "ok", "result": result.to_dict()}

    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Ingestion failed: {type(exc).__name__}: {exc}") from exc

    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


@app.post("/rag/reindex")
def reindex_rag(
    company_id: int | None = None,
    reset: bool = True,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
    batch_size: int = 64,
) -> dict[str, Any]:
    try:
        inserted_count = index_documents(
            company_id=company_id,
            reset=reset,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            batch_size=batch_size,
        )
        return {"status": "ok", "inserted_chunks": inserted_count}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Reindex failed: {type(exc).__name__}: {exc}") from exc


@app.post("/analysis/run")
def run_analysis(
    project_id: int | None = None,
    company_id: int | None = None,
    auto_approve: bool = True,
    thread_id: str = "ax-planner-api",
) -> dict[str, Any]:
    try:
        result = run_demo(
            project_id=project_id,
            company_id=company_id,
            thread_id=thread_id,
            auto_approve=auto_approve,
            verbose=False,
        )

        if "__interrupt__" in result:
            return {
                "status": "interrupted",
                "interrupt": str(result.get("__interrupt__")),
            }

        return {
            "status": "ok",
            "report_docx_path": result.get("report_docx_path"),
            "generation": result.get("report_data", {}).get("generation", {}),
            "citation_validation": result.get("report_data", {}).get("citation_validation", {}),
            "top_candidates": result.get("priority_ranking", {}).get("items", [])[:5],
            "errors": result.get("errors", []),
        }

    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Analysis failed: {type(exc).__name__}: {exc}") from exc


@app.post("/reviews/apply-ranking")
def apply_review_to_ranking(request: ReviewApplyRequest) -> dict[str, Any]:
    result = apply_human_review_to_ranking(
        priority_ranking=request.priority_ranking,
        human_review=request.human_review,
    )
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
    <h2>1. 문서 업로드 + RAG 색인</h2>
    <label>Company ID</label>
    <input id="companyId" type="number" value="1" />
    <label>Process ID(optional)</label>
    <input id="processId" type="number" placeholder="optional" />
    <label>File</label>
    <input id="file" type="file" />
    <button onclick="ingest()">Upload & Index</button>
  </section>

  <section>
    <h2>2. 분석 실행</h2>
    <label>Project ID(optional)</label>
    <input id="projectId" type="number" placeholder="optional" />
    <button onclick="runAnalysis()">Run Analysis</button>
  </section>

  <section>
    <h2>결과</h2>
    <pre id="output"></pre>
  </section>

<script>
function show(data) {
  document.getElementById('output').textContent = JSON.stringify(data, null, 2);
}

async function ingest() {
  const form = new FormData();
  const companyId = document.getElementById('companyId').value;
  const processId = document.getElementById('processId').value;
  const file = document.getElementById('file').files[0];
  form.append('company_id', companyId);
  if (processId) form.append('process_id', processId);
  if (!file) return show({error: 'file required'});
  form.append('file', file);
  form.append('index', 'true');

  const res = await fetch('/documents/ingest', {method: 'POST', body: form});
  show(await res.json());
}

async function runAnalysis() {
  const projectId = document.getElementById('projectId').value;
  const companyId = document.getElementById('companyId').value;
  const params = new URLSearchParams();
  if (projectId) params.append('project_id', projectId);
  if (companyId) params.append('company_id', companyId);
  params.append('auto_approve', 'true');
  const res = await fetch('/analysis/run?' + params.toString(), {method: 'POST'});
  show(await res.json());
}
</script>
</body>
</html>
"""
