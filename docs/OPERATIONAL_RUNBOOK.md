<!-- 파일 역할: 운영 점검, 장애 대응, preflight 실행 절차를 정리한 runbook이다. -->

# AX Delivery Planner Operational Runbook

이 문서는 AX Delivery Planner를 내부 PoC MVP로 운영할 때 필요한 점검, 실행, 장애 대응 절차를 정리한다.

## 1. 로컬/운영 공통 점검

```bash
python -m app.ops.preflight --json
```

운영 배포 전에는 strict mode를 사용한다.

```bash
python -m app.ops.preflight --strict
```

점검 항목:

- DATABASE_URL 설정 및 DB 연결
- OPENAI_API_KEY 설정
- production 환경의 APP_API_KEY / APP_JWT_SECRET 강도
- local 또는 S3/MinIO 문서 저장소 설정
- Agent sandbox 설정
- Graph node worker mode 설정
- Public web discovery provider/API key 설정
- vLLM endpoint 접근 가능성

## 2. DB 초기화 및 migration

```bash
python -m app.db.init_pgvector
python -m app.db.create_tables
python -m app.db.migrate_operational_hardening
```

## 3. Agent 품질 평가

```bash
python -m app.evaluation.agent_quality_eval --json
```

품질 gate:

```bash
python -m app.evaluation.agent_quality_eval \
  --strict \
  --min-status-accuracy 0.80 \
  --min-review-accuracy 0.90
```

기준:

- status_accuracy: 후보 상태 분류 정확도
- review_gate_accuracy: Human Review 필요 여부 판단 정확도
- confusion_matrix: expected status 대비 predicted status 분포

## 4. Agent Tool Sandbox

기본값은 direct mode이다.

```env
AGENT_TOOL_SANDBOX_MODE=direct
```

command-style tool을 Docker sandbox로 격리하려면 다음을 설정한다.

```env
AGENT_TOOL_SANDBOX_MODE=docker
AGENT_TOOL_SANDBOX_IMAGE=python:3.12-slim
AGENT_TOOL_SANDBOX_TIMEOUT_SECONDS=30
AGENT_TOOL_SANDBOX_NETWORK=none
```

Docker mode는 다음 제한을 적용한다.

- network none
- read-only filesystem
- cpu/memory 제한
- pids-limit
- cap-drop ALL
- no-new-privileges

추가로 command allowlist/denylist를 적용한다.

- 허용: python, python3, python3.10, python3.11, python3.12, pytest
- 차단: bash, sh, curl, wget, ssh, scp, nc, docker, kubectl, rm, mv, chmod, chown, sudo
- 차단 인자: --privileged, --network=host, --cap-add, --volume, -v, --mount

주의: command-style tool은 sandbox를 거치며, 일반 node는 runtime tool permission guard를 통해 권한을 검사한다.

## 5. Graph Node Worker 격리

Analysis Supervisor Graph의 모든 함수형 node는 `workerized_node()` wrapper를 거친다. 기본값은 기존과 동일한 direct 실행이다.

```env
GRAPH_NODE_EXECUTION_MODE=direct
```

각 node를 별도 Python worker process로 실행하려면 다음을 사용한다.

```env
GRAPH_NODE_EXECUTION_MODE=subprocess
GRAPH_NODE_WORKER_TIMEOUT_SECONDS=300
```

Docker worker mode도 지원한다.

```env
GRAPH_NODE_EXECUTION_MODE=docker
GRAPH_NODE_WORKER_IMAGE=ax-delivery-planner:latest
GRAPH_NODE_WORKER_TIMEOUT_SECONDS=300
```

권장 순서:

1. 개발/테스트: `direct`
2. 격리 검증: `subprocess`
3. 컨테이너 기반 운영 실험: `docker`

`human_review`는 LangGraph interrupt/resume context가 필요하므로 parent graph process에서 실행된다. 나머지 node는 worker mode 적용 대상이다.

Docker worker 환경 검증:

```bash
python -m app.ops.docker_worker_smoke --build-image --skip-vllm
```

vLLM까지 같이 확인하려면:

```bash
python -m app.ops.docker_worker_smoke --build-image --strict
```

이 smoke test는 다음을 확인한다.

- Docker daemon 접근 가능 여부
- `GRAPH_NODE_WORKER_IMAGE` 존재 또는 build 가능 여부
- worker container 내부에서 DB `SELECT 1` 가능 여부
- worker container 내부에서 vLLM endpoint socket 접근 가능 여부

macOS Docker Desktop에서는 container에서 host DB/vLLM 접근 시 `.env`의 host를 `host.docker.internal`로 맞추는 편이 안전하다.

## 6. Bootstrap 실행

```bash
python -m app.company_bootstrap.bootstrap \
  --company-name "삼성전자" \
  --stock-code "005930" \
  --official-url "https://www.samsung.com/sec/about-us/company-info/" \
  --official-url "https://www.samsung.com/sec/about-us/business-area/" \
  --official-url "https://www.samsung.com/sec/sustainability/overview/"
```

확인할 것:

- company_id
- project_id
- document_ids
- process_ids
- agent_trace
- idempotency.created_* / updated_*

같은 명령을 두 번 실행했을 때 중복 생성이 급증하면 idempotency 또는 unique index를 점검한다.

## 7. Analysis 실행

```bash
python -m app.main \
  --project-id <project_id> \
  --auto-approve \
  --reviewer-name "오재식" \
  --review-comment "Agent Evaluator, LLM Critic, Replan Loop 검증 결과를 확인한 뒤 1차 PoC 후보로 승인함." \
  --report-status reviewed \
  --verbose
```

Subprocess worker mode:

```bash
GRAPH_NODE_EXECUTION_MODE=subprocess python -m app.main \
  --project-id <project_id> \
  --auto-approve \
  --reviewer-name "오재식" \
  --review-comment "Subprocess worker mode 검증 후 승인" \
  --report-status reviewed \
  --verbose
```

정상 trace에는 다음이 포함되어야 한다.

```text
agent_evaluator
llm_critic
```

근거 부족 후보가 있으면 다음이 1회 추가될 수 있다.

```text
agent_replan
retrieve_context
```

## 8. Replan Loop 기준

Replan Loop는 다음 조건에서 실행된다.

- Agent Evaluator의 `additional_evidence_required_count > 0`
- `replan_attempts < 1`

기본 수행 내용:

- 기존 공식 URL의 같은 도메인에서 sitemap/link 기반 후보 URL 탐색
- ESG, governance, compliance, business, investor, report, policy 등 키워드 기반 URL 선별
- 최대 3개 공식 URL 추가 수집
- DB upsert
- RAG chunk 재색인
- retrieve_context 재실행

옵션으로 public web search를 켤 수 있다.

```env
EXTERNAL_WEB_DISCOVERY_ENABLED=true
EXTERNAL_WEB_SEARCH_PROVIDER=brave
BRAVE_SEARCH_API_KEY=<SET_KEY>
EXTERNAL_WEB_MAX_RESULTS=3
```

또는:

```env
EXTERNAL_WEB_DISCOVERY_ENABLED=true
EXTERNAL_WEB_SEARCH_PROVIDER=serpapi
SERPAPI_API_KEY=<SET_KEY>
EXTERNAL_WEB_MAX_RESULTS=3
```

Public web discovery는 Brave/SerpAPI 결과를 보조 출처로 사용한다. 소셜 도메인과 중복 URL은 제외하고, 결과 URL은 RAG에 색인되며 `replan_request.source_collection.public_web_search`에 기록된다.

API key 설정 여부는 preflight에서 검증된다.

```bash
python -m app.ops.preflight --json
```

한계:

- 검색엔진 기반 결과는 opt-in이다
- 검색 결과 품질은 provider/API 품질에 의존한다
- 내부 문서 업로드는 자동화하지 않는다

## 9. LLM Critic 장애 대응

LLM Critic은 optional이다. vLLM이 꺼져 있거나 JSON 파싱이 실패하면 deterministic fallback으로 전환된다.

확인할 field:

```text
agent_evaluation.items[].llm_critic.critic_mode
```

값:

- `llm_critic`: vLLM Critic 사용
- `deterministic_fallback`: vLLM 실패 또는 파싱 실패

fallback이 반복되면 다음을 확인한다.

```bash
curl http://localhost:8000/v1/models
```

## 10. Observability

운영 compose에는 Prometheus와 Grafana가 포함된다.

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

접속:

- API: `http://localhost:8001`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`

Grafana 기본 계정은 `.env`의 값을 사용한다.

```env
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=admin
```

Prometheus scrape 대상:

```text
api:8001/metrics
```

HTTP 지표:

- `ax_http_requests_total`
- `ax_http_request_latency_seconds_sum`
- `ax_http_request_latency_seconds_max`

Agent node 지표:

- `ax_agent_node_runs_total{node,mode,status}`
- `ax_agent_node_latency_seconds_sum{node,mode,status}`
- `ax_agent_node_latency_seconds_max{node,mode,status}`

Grafana dashboard는 다음 panel을 포함한다.

- HTTP request rate
- HTTP average/max latency
- Agent node runs
- Agent node average/max latency
- Agent node failures

기본 alert rule:

- 5분 동안 5xx error rate 5% 초과
- 5분 평균 HTTP latency 10초 초과
- 10분 동안 Agent node failure 1건 이상
- Agent node max latency 60초 초과

## 11. 보고서 검토

보고서에 포함되어야 하는 핵심 섹션:

- AI Governance 및 Compliance Assessment
- Agent Evaluation 및 신뢰도 검증
- PoC 실행계획
- Human Review 및 의사결정 기록

Agent Evaluation 섹션에서 확인할 항목:

- Confidence
- Critic Adjusted Confidence
- Evidence
- Data
- Rationale
- Risk Uncertainty
- Critic Verdict
- Human Review 여부
- 추가 근거 필요 여부

## 12. CI

GitHub Actions는 다음을 수행한다.

- `pytest`
- `python -m app.evaluation.agent_quality_eval --strict ...`
- `python -m app.ops.preflight --json --skip-optional`

CI가 실패하면 우선 테스트 로그에서 다음 순서로 본다.

1. import/schema 오류
2. Agent quality gate 정확도 하락
3. preflight DB/env 오류
4. sandbox command allowlist 오류
5. metrics/dashboard query 오류

## 13. 운영 전 남은 선택 과제

- 운영용 React/Vue wizard UI
- 100개 이상 Agent 품질 평가셋 확대
- 한국 AI 기본법 조항별 법령 원문 mapping
