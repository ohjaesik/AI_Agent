<!-- 파일 역할: LLM 출력 품질을 deterministic evaluator와 분리해 검증하는 방법을 설명한다. -->

# LLM Quality Evaluation

이 문서는 AX Delivery Planner에서 LLM이 개입하는 구간을 Agent Evaluator 품질 평가와 분리해 검증하는 방법을 설명한다.

## 목적

기존 `app/evaluation/agent_quality_eval.py`는 deterministic Agent Evaluator의 상태 판정과 Human Review gate를 검증한다. 반면 `app/evaluation/llm_quality_eval.py`는 LLM이 직접 관여하는 다음 구간의 운영 안정성을 별도 측정한다.

- `company_process_discovery`: 공식자료 기반 후보 업무 생성
- `llm_critic`: Agent Evaluator 결과에 대한 second-opinion 검토
- `report_writer`: 보고서 문단 재작성 및 citation 유지

핵심 의사결정은 deterministic rule과 quality gate로 관리하고, LLM은 JSON 안정성, schema 준수, 근거 label 사용, citation validation, fallback 발생률 중심으로 평가한다.

## 평가 지표

| Metric | 의미 |
|---|---|
| `pass_rate` | 전체 LLM 품질 케이스 통과율 |
| `json_parse_success_rate` | LLM 출력 또는 캡처 payload가 JSON으로 파싱되는 비율 |
| `schema_valid_rate` | 대상별 필수 schema를 만족하는 비율 |
| `fallback_free_rate` | deterministic/template fallback 없이 처리된 비율 |
| `average_primary_score` | 대상별 핵심 체크 항목 평균 점수 |

대상별로 추가 확인하는 항목은 다음과 같다.

| Target | 주요 체크 |
|---|---|
| `company_process_discovery` | 후보 수 범위, 필수 필드, evidence label 유효성, 1~5 점수 범위 |
| `llm_critic` | verdict 유효성, confidence adjustment 범위, unsafe pass 차단, fallback 여부 |
| `report_writer` | section/paragraph 구조, citation validation 통과 여부, fallback 여부 |

## 실행 방법

기본 케이스 실행:

```bash
python -m app.evaluation.llm_quality_eval --json
```

CSV와 Markdown 보고서 생성:

```bash
python -m app.evaluation.llm_quality_eval \
  --csv outputs/llm_quality_eval.csv \
  --markdown outputs/llm_quality_eval.md
```

품질 게이트를 강제하려면 `--strict`를 사용한다.

```bash
python -m app.evaluation.llm_quality_eval \
  --strict \
  --min-pass-rate 0.90 \
  --min-json-parse-success-rate 0.95 \
  --min-schema-valid-rate 0.90 \
  --min-fallback-free-rate 0.70
```

모델 교체 또는 prompt 수정 후에는 실제 LLM 응답을 JSONL case로 캡처해 `--case-path`로 비교할 수 있다.

```bash
python -m app.evaluation.llm_quality_eval \
  --case-path outputs/llm_quality_cases_gemma_candidate.jsonl \
  --strict
```

## 실제 LLM 출력 JSONL 캡처

`llm_quality_eval.py`는 LLM을 직접 호출하지 않고 JSONL case를 검증한다. 실제 모델 출력물을 평가하려면 먼저 워크플로우 실행 결과 state를 JSON으로 저장한 뒤 `capture_llm_quality_cases.py`로 JSONL을 만든다.

예시:

```python
import json
from pathlib import Path

final_state = graph.invoke(input_state)
Path("outputs/workflow_state_real.json").write_text(
    json.dumps(final_state, ensure_ascii=False, indent=2, default=str),
    encoding="utf-8",
)
```

저장한 state에서 LLM 품질 케이스를 추출한다.

```bash
python -m app.evaluation.capture_llm_quality_cases \
  --state outputs/workflow_state_real.json \
  --output outputs/llm_quality_cases_real.jsonl \
  --case-prefix gemma_real
```

그 다음 추출된 JSONL을 평가한다.

```bash
python -m app.evaluation.llm_quality_eval \
  --case-path outputs/llm_quality_cases_real.jsonl \
  --strict \
  --min-pass-rate 0.90 \
  --min-json-parse-success-rate 0.95 \
  --min-schema-valid-rate 0.90 \
  --min-fallback-free-rate 0.70
```

모델 교체 전후를 regression 기준으로 비교하려면 현재 LLM Critic verdict를 expected verdict로 고정할 수 있다.

```bash
python -m app.evaluation.capture_llm_quality_cases \
  --state outputs/workflow_state_real.json \
  --output outputs/llm_quality_cases_baseline.jsonl \
  --case-prefix baseline_gemma \
  --freeze-current-verdict
```

## 케이스 형식

기본 케이스 파일은 `tests/data/llm_quality_cases.jsonl`에 둔다. 각 줄은 하나의 JSON object다.

### company_process_discovery

```json
{
  "case_id": "discovery_schema_valid",
  "target": "company_process_discovery",
  "allowed_labels": ["[SRC-1]"],
  "expected_min_processes": 5,
  "expected_max_processes": 8,
  "payload": {
    "processes": []
  }
}
```

### llm_critic

```json
{
  "case_id": "critic_needs_review_valid",
  "target": "llm_critic",
  "expected_verdict": "needs_review",
  "expected_not_pass": true,
  "payload": {
    "critic_verdict": "needs_review",
    "critic_confidence_adjustment": -0.05,
    "critic_reason": "검토 필요",
    "missing_evidence": [],
    "review_questions": [],
    "critic_mode": "llm_critic"
  }
}
```

### report_writer

```json
{
  "case_id": "report_writer_citation_valid",
  "target": "report_writer",
  "expected_min_paragraphs": 1,
  "evidence_items": [
    {"citation_label": "[DOC-1]", "summary": "공식 문서 근거"}
  ],
  "payload": {
    "sections": [
      {
        "heading": "1. 분석 개요",
        "blocks": [
          {"type": "paragraph", "text": "근거 문장 [DOC-1]"}
        ]
      }
    ],
    "generation": {"mode": "vllm_report_writer"}
  }
}
```

## 테스트

```bash
pytest tests/test_llm_quality_eval.py tests/test_capture_llm_quality_cases.py
```

전체 품질 평가와 함께 돌릴 경우:

```bash
pytest tests/test_agent_quality_eval.py tests/test_llm_quality_eval.py tests/test_capture_llm_quality_cases.py
```
