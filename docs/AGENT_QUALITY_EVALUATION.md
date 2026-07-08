# Agent Quality Evaluation

Agent Evaluator의 상태 분류와 Human Review gate 품질을 점검하기 위한 평가 절차다.

## 평가셋 구분

평가셋은 두 종류로 분리한다.

### 1. Regression set

정책 회귀 테스트용 평가셋이다. 현재 evaluator 정책이 깨졌는지 확인하는 목적이며, 일반화 성능으로 해석하지 않는다.

구성:

- `tests/data/agent_quality_gold.jsonl`: 수동 JSONL seed cases 50개
- `app/evaluation/agent_quality_gold_generator.py`: deterministic extension cases 50개

총 100개 case를 regression set으로 사용한다.

### 2. Blind holdout set

일반화 점검용 독립 평가셋이다. threshold 튜닝에 직접 사용하지 않는 것을 원칙으로 한다.

구성:

- `tests/data/blind_holdout_gold.jsonl`: holdout v1, 수동 cases 40개

holdout set은 regression보다 낮은 gate 기준을 사용한다. holdout v1도 synthetic 성격이 있으므로, 실제 graph 실행 결과에서 추출한 borderline case를 계속 추가한다.

## 실행

Regression set:

```bash
python -m app.evaluation.agent_quality_eval \
  --dataset regression \
  --json \
  --csv outputs/agent_quality_regression.csv \
  --markdown outputs/agent_quality_regression.md
```

Blind holdout set:

```bash
python -m app.evaluation.agent_quality_eval \
  --dataset holdout \
  --json \
  --csv outputs/agent_quality_holdout.csv \
  --markdown outputs/agent_quality_holdout.md
```

Regression strict gate:

```bash
python -m app.evaluation.agent_quality_eval \
  --dataset regression \
  --strict \
  --min-status-accuracy 0.95 \
  --min-review-accuracy 0.95 \
  --min-status-macro-f1 0.95 \
  --min-review-f1 0.95
```

Holdout strict gate:

```bash
python -m app.evaluation.agent_quality_eval \
  --dataset holdout \
  --strict \
  --min-status-accuracy 0.85 \
  --min-review-accuracy 0.85 \
  --min-status-macro-f1 0.80 \
  --min-review-f1 0.85
```

Regression seed만 평가하려면:

```bash
python -m app.evaluation.agent_quality_eval --dataset regression --no-generated
```

## 실제 Graph 결과 기반 holdout 추가 절차

현재 holdout v1은 유지하고, 실제 graph 실행 결과에서 새 unlabeled candidate를 뽑아 사람이 라벨링한다.

1. Graph state 저장:

```bash
GRAPH_NODE_EXECUTION_MODE=subprocess python -m app.main \
  --project-id 1 \
  --auto-approve \
  --reviewer-name "오재식" \
  --review-comment "Holdout labeling 후보 추출용 실행." \
  --report-status reviewed \
  --verbose \
  --state-json-output outputs/graph_state_for_labeling.json
```

2. Borderline candidate를 CSV/JSONL로 추출:

```bash
python -m app.evaluation.export_holdout_candidates \
  --state-json outputs/graph_state_for_labeling.json \
  --borderline-only \
  --case-id-prefix graph-holdout-v2 \
  --csv outputs/unlabeled_holdout_candidates.csv \
  --jsonl outputs/unlabeled_holdout_candidates.jsonl
```

3. 사람이 CSV의 두 칸을 수동 라벨링한다.

- `expected_status`
- `expected_requires_human_review`

4. 라벨링 완료 후 CSV label을 JSONL gold로 병합한다.

```bash
python -m app.evaluation.finalize_labeled_holdout \
  --unlabeled-jsonl outputs/unlabeled_holdout_candidates.jsonl \
  --labeled-csv outputs/unlabeled_holdout_candidates.csv \
  --output-jsonl outputs/labeled_holdout_gold.jsonl
```

5. 검토 후 holdout 파일에 추가한다.

```bash
python -m app.evaluation.finalize_labeled_holdout \
  --unlabeled-jsonl outputs/unlabeled_holdout_candidates.jsonl \
  --labeled-csv outputs/unlabeled_holdout_candidates.csv \
  --output-jsonl outputs/labeled_holdout_gold.jsonl \
  --append-to tests/data/blind_holdout_gold.jsonl
```

권장 추가 기준:

- confidence 0.55~0.78 사이
- evidence coverage 0.20~0.55 사이
- weak evidence but nonzero evidence
- compliance와 evidence 판단이 충돌하는 후보
- replan 후에도 애매한 후보

## 주요 지표

- `evaluation_set`: `regression`, `holdout`, 또는 `custom`
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

Regression set은 정책 일관성 검증용이다. 여기서 1.0이 나오더라도 일반화 성능으로 표현하지 않는다.

Holdout set은 독립 검증용이다. 운영 전 최소 기준은 다음과 같다.

- status_accuracy >= 0.85
- review_gate_accuracy >= 0.85
- status_macro_f1 >= 0.80
- review_gate_f1 >= 0.85

`misclassified`가 발생하면 우선 다음 순서로 확인한다.

1. holdout label이 현재 정책 기준과 충돌하지 않는지
2. evaluator threshold가 지나치게 보수/완화되어 있는지
3. compliance mapping이 blocked/sensitive/enhanced를 의도대로 반영하는지
4. replan evidence lift가 과도하게 추천 상태를 밀어 올리는지
5. 동일 케이스를 보고 threshold를 바로 맞추지 말고, 유사 케이스가 반복될 때만 정책을 변경할지 검토한다.
