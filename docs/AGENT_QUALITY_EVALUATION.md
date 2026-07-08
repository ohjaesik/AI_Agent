# Agent Quality Evaluation

Agent Evaluator의 상태 분류와 Human Review gate 품질을 점검하기 위한 평가 절차다.

## 평가셋 구성

기본 평가셋은 다음 두 묶음을 합산한다.

- `tests/data/agent_quality_gold.jsonl`: 수동 JSONL seed cases 50개
- `app/evaluation/agent_quality_gold_generator.py`: deterministic extension cases 50개

총 100개 case를 기본 평가 대상으로 사용한다.

평가 case는 다음 유형을 포함한다.

- 정상 recommended 후보
- 중간 근거/부분 rationale 후보
- sensitive_review 후보
- enhanced_review 후보
- blocked/excluded 후보
- evidence_insufficient 후보
- post-replan evidence lift 후보

## 실행

기본 요약 지표:

```bash
python -m app.evaluation.agent_quality_eval
```

JSON 전체 출력:

```bash
python -m app.evaluation.agent_quality_eval --json
```

CSV 저장:

```bash
python -m app.evaluation.agent_quality_eval \
  --json \
  --csv outputs/agent_quality_eval.csv
```

Strict gate:

```bash
python -m app.evaluation.agent_quality_eval \
  --strict \
  --min-status-accuracy 0.80 \
  --min-review-accuracy 0.90 \
  --min-status-macro-f1 0.75 \
  --min-review-f1 0.90
```

JSONL seed만 평가하려면:

```bash
python -m app.evaluation.agent_quality_eval --no-generated
```

## 주요 지표

- `status_accuracy`: expected status와 predicted status의 전체 일치율
- `status_macro_f1`: recommended/human_review_required/evidence_insufficient/excluded 등 status별 F1의 macro average
- `status_weighted_f1`: support를 반영한 status weighted F1
- `review_gate_accuracy`: Human Review 필요 여부의 전체 일치율
- `review_gate_f1`: Human Review positive class 기준 F1
- `confusion_matrix`: expected status 대비 predicted status matrix
- `status_report`: status별 precision/recall/F1/support
- `review_gate_report`: Human Review gate의 precision/recall/F1/TP/FP/FN/TN
- `misclassified`: status 또는 review gate가 틀린 case 목록

## 해석 기준

운영 전 최소 기준:

- status_accuracy >= 0.80
- review_gate_accuracy >= 0.90
- status_macro_f1 >= 0.75
- review_gate_f1 >= 0.90

`misclassified`가 발생하면 우선 다음 순서로 확인한다.

1. expected label이 현재 정책 기준과 맞는지
2. evaluator threshold가 지나치게 보수/완화되어 있는지
3. compliance mapping이 blocked/sensitive/enhanced를 의도대로 반영하는지
4. replan evidence lift가 과도하게 추천 상태를 밀어 올리는지
