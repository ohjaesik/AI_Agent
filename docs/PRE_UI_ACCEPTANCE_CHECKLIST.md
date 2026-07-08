# Pre-UI Acceptance Checklist

UI 구현 전 백엔드, Supervisor Graph, 평가 gate가 안정화되었는지 확인하는 기준이다.

## 1. Local Smoke

```bash
git pull origin main
pytest
python -m app.ops.preflight --json
```

Docker를 사용하지 않는 로컬 개발 환경 권장값:

```env
GRAPH_NODE_EXECUTION_MODE=subprocess
AGENT_TOOL_SANDBOX_MODE=direct
EXTERNAL_WEB_DISCOVERY_ENABLED=false
```

## 2. Agent Quality Gate

100개 평가셋 기준 strict gate:

```bash
python -m app.evaluation.agent_quality_eval \
  --strict \
  --min-status-accuracy 0.80 \
  --min-review-accuracy 0.90 \
  --min-status-macro-f1 0.75 \
  --min-review-f1 0.90 \
  --json \
  --csv outputs/agent_quality_eval.csv \
  --markdown outputs/agent_quality_eval.md
```

통과 기준:

- `quality_gate.passed=true`
- `status_accuracy >= 0.80`
- `review_gate_accuracy >= 0.90`
- `status_macro_f1 >= 0.75`
- `review_gate_f1 >= 0.90`
- 가능하면 `misclassified=[]`

## 3. Graph Execution

```bash
GRAPH_NODE_EXECUTION_MODE=subprocess python -m app.main \
  --project-id 1 \
  --auto-approve \
  --reviewer-name "오재식" \
  --review-comment "Pre-UI acceptance check 후 승인함." \
  --report-status reviewed \
  --verbose
```

정상 기준:

- `load_project_data` success
- `retrieve_context` success
- `compliance_assessment` success
- `priority_ranking` success
- `agent_evaluator` success
- `llm_critic` success
- `human_review` success
- `poc_delivery_planner` success
- `report_writer` success
- `docx_generator` success

## 4. Replan/Public Web Discovery

Public web discovery 비활성 기본값:

```env
EXTERNAL_WEB_DISCOVERY_ENABLED=false
```

실제 검색 검증이 필요할 때만 Brave 또는 SerpAPI key를 설정한다.

```bash
python -m app.ops.public_web_search_smoke \
  --company-name "Samsung Electronics" \
  --query-term sustainability \
  --query-term governance \
  --max-results 3 \
  --strict
```

정상 기준:

- `ok=true`
- `result_count > 0`
- graph 실행 시 `public_web_url_count > 0`
- replan 후 `replan_evidence_lift > 0`

## 5. Report Output

보고서 생성 기준:

- `report_docx_path` 존재
- `citation_valid=True`
- `invalid_labels=[]`
- `paragraphs_without_citation=0`
- `report_sections >= 10`

문서 확인:

```bash
open outputs/AX_Delivery_Planner_Report_1.docx
```

## 6. CI Gate

GitHub Actions는 다음을 수행해야 한다.

- `pytest`
- 100개 Agent quality eval strict gate
- CSV/Markdown quality report artifact 저장
- `preflight --json --skip-optional`

## 7. UI 착수 가능 기준

아래 조건을 만족하면 UI 구현으로 넘어간다.

- Local tests 통과
- Agent quality gate 통과
- Graph end-to-end 실행 성공
- DOCX report 생성 성공
- CI 통과
- public web discovery는 opt-in으로 smoke 검증 가능
- Docker worker는 운영 검증용 선택 사항으로 남김

## 8. UI 외 남은 선택 과제

필수는 아니며, 운영 전 고도화 과제다.

- Docker Desktop 설치 후 docker worker smoke test
- Grafana dashboard 실제 Agent panel 확인
- 한국 AI 기본법 공식 조문 번호 mapping 확정
- 외부 배포 전 법무/보안 문구 검토
- 운영용 사용자 권한/조직 role 설계
