"""외부 holdout 평가 데이터 생성 로직을 검증한다.
"""

import json

from app.evaluation.external_holdout_builder import build_external_holdout_cases, write_jsonl


def test_online_retail_mapping_recommends_inventory_agent(tmp_path):
    csv_path = tmp_path / "online_retail.csv"
    csv_path.write_text(
        "InvoiceNo,StockCode,Description,Quantity,UnitPrice,Country\n"
        "536365,85123A,WHITE HANGING HEART T-LIGHT HOLDER,6,2.55,United Kingdom\n",
        encoding="utf-8",
    )

    cases = build_external_holdout_cases("online_retail", csv_path, "retail")

    assert cases[0]["case_id"] == "retail-001"
    assert cases[0]["candidate_agent_name"] == "Retail Inventory Reorder Agent"
    assert cases[0]["expected_status"] == "recommended"
    assert cases[0]["expected_requires_human_review"] is False


def test_online_retail_customer_mapping_requires_review(tmp_path):
    csv_path = tmp_path / "online_retail.csv"
    csv_path.write_text(
        "InvoiceNo,Description,Quantity,UnitPrice,CustomerID\n"
        "536365,WHITE HANGING HEART T-LIGHT HOLDER,6,2.55,17850\n",
        encoding="utf-8",
    )

    cases = build_external_holdout_cases("online_retail", csv_path, "retail")

    assert cases[0]["candidate_agent_name"] == "Retail Customer Segmentation Agent"
    assert cases[0]["expected_status"] == "human_review_required"
    assert cases[0]["expected_requires_human_review"] is True
    assert cases[0]["compliance"]["compliance_level"] == "sensitive_review"


def test_credit_default_mapping_blocks_automated_rejection(tmp_path):
    csv_path = tmp_path / "credit.csv"
    csv_path.write_text(
        "LIMIT_BAL,PAY_0,PAY_2,default_payment_next_month\n"
        "20000,2,2,1\n",
        encoding="utf-8",
    )

    cases = build_external_holdout_cases("credit_default", csv_path, "credit")

    assert cases[0]["candidate_agent_name"] == "Automated Credit Rejection Agent"
    assert cases[0]["expected_status"] == "excluded"
    assert cases[0]["expected_requires_human_review"] is True
    assert cases[0]["compliance"]["blocked"] is True


def test_process_mining_mapping_marks_missing_timestamp_insufficient(tmp_path):
    csv_path = tmp_path / "event_log.csv"
    csv_path.write_text(
        "case_id,activity,resource\n"
        "1,Approve invoice,clerk\n",
        encoding="utf-8",
    )

    cases = build_external_holdout_cases("process_mining", csv_path, "proc")

    assert cases[0]["candidate_agent_name"] == "Process Event Log Readiness Agent"
    assert cases[0]["expected_status"] == "evidence_insufficient"
    assert cases[0]["expected_requires_human_review"] is True


def test_external_holdout_builder_writes_jsonl(tmp_path):
    csv_path = tmp_path / "bank.csv"
    csv_path.write_text(
        "age,job,loan,campaign,y\n"
        "42,admin.,yes,4,no\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "external_holdout.jsonl"

    cases = build_external_holdout_cases("bank_marketing", csv_path, "bank", max_cases=1)
    write_jsonl(output_path, cases)

    payload = json.loads(output_path.read_text(encoding="utf-8").strip())
    assert payload["case_id"] == "bank-001"
    assert payload["expected_status"] == "human_review_required"
    assert payload["expected_requires_human_review"] is True
