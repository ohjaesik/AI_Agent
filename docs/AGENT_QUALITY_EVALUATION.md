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

현재 구성:

- `tests/data/blind_holdout_gold.jsonl`: holdout v1, 수동 cases 40개

주의: holdout v1은 synthetic 성격이 있으므로 최종 일반화 성능으로 표현하지 않는다. 이후 holdout v2는 외부 공개 데이터 기반으로 새로 구성한다.

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

## Holdout v2 외부 데이터 구성 방향

수동 라벨링 CSV 방식은 사용하지 않는다. 대신 외부 공개 데이터셋에서 업무 도메인과 리스크 유형을 가져와 holdout v2를 구성한다.

우선순위:

1. Process mining event logs
   - 업무 프로세스, 이벤트 로그, 처리 흐름 기반 케이스를 만들 수 있음
   - `recommended`, `human_review_required`, `evidence_insufficient` 경계 케이스 구성에 적합

2. Bank marketing / credit decision data
   - 금융·마케팅 의사결정 도메인
   - `human_review_required`, `excluded` 케이스 구성에 적합

3. Online retail transaction data
   - 상품 추천, 수요예측, 고객 세분화, 재고/주문 프로세스
   - 저위험 자동화와 개인정보 경계 케이스를 함께 만들 수 있음

Holdout v2 생성 원칙:

- evaluator threshold를 보고 라벨을 맞추지 않는다.
- 외부 데이터의 도메인 설명, feature 성격, 업무 영향도를 기준으로 라벨을 붙인다.
- 같은 템플릿에서 여러 케이스를 찍어내지 않는다.
- confidence/evidence 값이 너무 깨끗하게 분리되지 않도록 한다.
- 최소 30개 이상을 추가하고, 가능하면 50개 이상으로 확장한다.

## External holdout builder

외부 CSV를 평가용 JSONL case로 변환한다.

지원 dataset type:

- `online_retail`
- `bank_marketing`
- `credit_default`
- `process_mining`

예시:

```bash
python -m app.evaluation.external_holdout_builder \
  --dataset-type online_retail \
  --input data/external/online_retail.csv \
  --case-id-prefix ext-retail \
  --process-id-start 20000 \
  --max-cases 30 \
  --output-jsonl outputs/external_holdout_v2.jsonl
```

여러 데이터셋을 하나의 holdout v2로 합칠 때는 `--append`를 사용한다.

```bash
python -m app.evaluation.external_holdout_builder \
  --dataset-type bank_marketing \
  --input data/external/bank_marketing.csv \
  --case-id-prefix ext-bank \
  --process-id-start 21000 \
  --max-cases 20 \
  --output-jsonl outputs/external_holdout_v2.jsonl \
  --append

python -m app.evaluation.external_holdout_builder \
  --dataset-type credit_default \
  --input data/external/credit_default.csv \
  --case-id-prefix ext-credit \
  --process-id-start 22000 \
  --max-cases 20 \
  --output-jsonl outputs/external_holdout_v2.jsonl \
  --append
```

생성한 외부 holdout은 custom gold path로 평가한다.

```bash
python -m app.evaluation.agent_quality_eval \
  --gold-path outputs/external_holdout_v2.jsonl \
  --strict \
  --min-status-accuracy 0.85 \
  --min-review-accuracy 0.85 \
  --min-status-macro-f1 0.80 \
  --min-review-f1 0.85 \
  --json \
  --csv outputs/agent_quality_external_holdout_v2.csv \
  --markdown outputs/agent_quality_external_holdout_v2.md
```

Mapping summary:

- Online retail 재고·주문 자동화: `recommended`
- Online retail 고객 세분화: `human_review_required`
- Bank marketing targeting: `human_review_required`
- Credit risk triage: `human_review_required`
- Automated credit rejection: `excluded`
- 일반 process bottleneck 분석: `recommended`
- 인사·성과·징계성 process monitoring: `human_review_required`
- 필수 event/log/source 부족: `evidence_insufficient`

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
