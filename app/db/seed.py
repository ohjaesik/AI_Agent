# app/db/seed.py

"""데모용 초기 데이터를 DB에 넣는 script.

로컬 테스트에서 회사/프로젝트/업무/문서 예시가 필요할 때 사용한다.
"""

from __future__ import annotations

import argparse

from app.db.crud import delete_seed_data
from app.db.database import SessionLocal
from app.db.models import (
    AnalysisProject,
    BusinessProcess,
    Company,
    Department,
    EnterpriseSystem,
    ProcessDocument,
)


def seed_company(db):
    """seed_company 함수. 데모용 초기 데이터를 DB에 넣는 script. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    company = Company(
        name="Hanbit Precision Manufacturing",
        industry="자동차 부품 제조",
        size="중견 제조기업",
        description=(
            "자동차 전장 부품과 금속 가공 부품을 생산하는 중견 제조기업이다. "
            "MES, ERP, QMS, CMMS를 보유하고 있으나 업무 문서와 이력 데이터가 "
            "부서별 시스템에 분산되어 있어 AX 전환 우선순위 판단에 어려움이 있다."
        ),
    )
    db.add(company)
    db.flush()
    return company


def seed_departments(db, company_id: int):
    """seed_departments 함수. 데모용 초기 데이터를 DB에 넣는 script. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    departments = [
        Department(
            company_id=company_id,
            name="생산관리팀",
            role="생산계획, 공정 운영, 작업지시, 생산실적 관리를 담당한다.",
            main_pain_points="작업표준서 검색 지연, 생산 이슈 공유 누락, 공정 병목 파악 지연",
        ),
        Department(
            company_id=company_id,
            name="설비정비팀",
            role="설비 예방정비, 고장 대응, 부품 교체, 정비 이력 관리를 담당한다.",
            main_pain_points="유사 고장 이력 검색 어려움, 정비 조치 지식의 개인 의존",
        ),
        Department(
            company_id=company_id,
            name="품질관리팀",
            role="검사, 불량 분석, 고객 클레임 대응, 품질 리포트 작성을 담당한다.",
            main_pain_points="불량 원인 분석 지연, QMS와 MES 데이터 비교 작업 반복",
        ),
        Department(
            company_id=company_id,
            name="안전관리팀",
            role="월간 안전점검, 위험요인 관리, 사고 보고, 안전교육 관리를 담당한다.",
            main_pain_points="점검표 작성 반복, 위험요인 보고서 작성 시간 과다",
        ),
        Department(
            company_id=company_id,
            name="구매자재팀",
            role="구매 발주, 납기 관리, 재고 관리, 공급사 조건 검토를 담당한다.",
            main_pain_points="발주 조건 검토 누락 가능성, 재고 부족과 과잉재고 반복",
        ),
        Department(
            company_id=company_id,
            name="IT기획팀",
            role="ERP, MES, QMS, 그룹웨어 운영과 AX/DX 과제 기획을 담당한다.",
            main_pain_points="부서별 AI Agent 도입 요구가 증가하지만 PoC 우선순위 판단 기준이 부족함",
        ),
    ]

    db.add_all(departments)
    db.flush()
    return {department.name: department for department in departments}


def seed_systems(db, company_id: int):
    """seed_systems 함수. 데모용 초기 데이터를 DB에 넣는 script. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    systems = [
        EnterpriseSystem(
            company_id=company_id,
            name="SAP ERP",
            system_type="ERP",
            owner_department="구매자재팀",
            data_access_level=3,
            api_available=True,
            description="구매, 자재, 회계, 원가 정보를 관리하는 핵심 시스템",
        ),
        EnterpriseSystem(
            company_id=company_id,
            name="SmartMES",
            system_type="MES",
            owner_department="생산관리팀",
            data_access_level=4,
            api_available=True,
            description="생산계획, 작업지시, 공정 실적, 설비 상태 일부를 관리하는 시스템",
        ),
        EnterpriseSystem(
            company_id=company_id,
            name="Q-Track",
            system_type="QMS",
            owner_department="품질관리팀",
            data_access_level=3,
            api_available=True,
            description="검사 결과, 불량 유형, 고객 클레임, 품질 리포트를 관리하는 시스템",
        ),
        EnterpriseSystem(
            company_id=company_id,
            name="FixBase",
            system_type="CMMS",
            owner_department="설비정비팀",
            data_access_level=3,
            api_available=False,
            description="설비 고장 이력, 정비 조치, 부품 교체 이력을 관리하는 시스템",
        ),
        EnterpriseSystem(
            company_id=company_id,
            name="SafeWorks",
            system_type="Safety Management",
            owner_department="안전관리팀",
            data_access_level=2,
            api_available=False,
            description="안전점검표, 사고보고서, 조치현황을 관리하는 시스템",
        ),
        EnterpriseSystem(
            company_id=company_id,
            name="WarehouseOne",
            system_type="WMS",
            owner_department="구매자재팀",
            data_access_level=3,
            api_available=True,
            description="창고 입출고, 재고 수량, LOT 정보를 관리하는 시스템",
        ),
        EnterpriseSystem(
            company_id=company_id,
            name="Groupware",
            system_type="Collaboration",
            owner_department="IT기획팀",
            data_access_level=2,
            api_available=True,
            description="회의록, 공지, 문서 결재, 협업 메시지를 관리하는 시스템",
        ),
    ]

    db.add_all(systems)
    db.flush()
    return systems


def seed_processes(db, company_id: int, departments: dict[str, Department]):
    """seed_processes 함수. 데모용 초기 데이터를 DB에 넣는 script. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    processes = [
        BusinessProcess(
            company_id=company_id,
            department_id=departments["생산관리팀"].id,
            name="SOP 검색",
            target_user="생산 작업자, 생산관리자",
            problem="작업표준서가 공유폴더, 그룹웨어, MES 첨부파일에 분산되어 검색 시간이 오래 걸린다.",
            current_workflow="작업자가 공정명과 제품명을 기준으로 문서를 직접 검색하고, 찾지 못하면 선임자에게 문의한다.",
            weekly_hours=8,
            hourly_cost=40000,
            expected_effect=4,
            repeatability=5,
            document_dependency=5,
            decision_complexity=2,
            data_accessibility=5,
            tech_feasibility=5,
            user_acceptance=5,
            risk_score=2,
            implementation_cost_score=2,
            security_level="internal",
            candidate_agent_name="SOP 질의응답 Agent",
        ),
        BusinessProcess(
            company_id=company_id,
            department_id=departments["설비정비팀"].id,
            name="설비 고장 이력 검색",
            target_user="설비정비 담당자",
            problem="유사 설비 고장 원인과 조치 이력을 찾기 어렵고, 일부 지식이 개인 경험에 의존한다.",
            current_workflow="정비 담당자가 CMMS, 엑셀, 작업일지를 별도로 조회해 유사 사례를 찾는다.",
            weekly_hours=10,
            hourly_cost=45000,
            expected_effect=5,
            repeatability=4,
            document_dependency=4,
            decision_complexity=4,
            data_accessibility=3,
            tech_feasibility=4,
            user_acceptance=4,
            risk_score=3,
            implementation_cost_score=3,
            security_level="internal",
            candidate_agent_name="설비 고장 이력 기반 정비 추천 Agent",
        ),
        BusinessProcess(
            company_id=company_id,
            department_id=departments["품질관리팀"].id,
            name="품질 불량 원인 분석",
            target_user="품질관리자",
            problem="불량 발생 시 QMS, MES, 검사 리포트를 수작업으로 비교해 원인 후보 도출이 지연된다.",
            current_workflow="품질 담당자가 불량 유형, 생산조건, 설비 상태, 검사 결과를 엑셀로 정리해 분석한다.",
            weekly_hours=12,
            hourly_cost=45000,
            expected_effect=5,
            repeatability=4,
            document_dependency=4,
            decision_complexity=5,
            data_accessibility=3,
            tech_feasibility=3,
            user_acceptance=4,
            risk_score=3,
            implementation_cost_score=4,
            security_level="confidential",
            candidate_agent_name="품질 불량 원인 분석 Agent",
        ),
        BusinessProcess(
            company_id=company_id,
            department_id=departments["안전관리팀"].id,
            name="안전 점검 리포트 작성",
            target_user="안전관리자",
            problem="월간 안전점검 결과를 엑셀로 작성한 뒤 보고서에 다시 정리하는 반복 작업이 많다.",
            current_workflow="안전관리자가 체크리스트를 작성하고 위험 항목과 조치사항을 월간 보고서로 재작성한다.",
            weekly_hours=6,
            hourly_cost=40000,
            expected_effect=4,
            repeatability=5,
            document_dependency=5,
            decision_complexity=3,
            data_accessibility=4,
            tech_feasibility=4,
            user_acceptance=4,
            risk_score=3,
            implementation_cost_score=2,
            security_level="internal",
            candidate_agent_name="안전 점검 리포트 Agent",
        ),
        BusinessProcess(
            company_id=company_id,
            department_id=departments["품질관리팀"].id,
            name="고객 클레임 대응",
            target_user="품질/CS 담당자",
            problem="고객 클레임 접수 후 원인 추적과 답변 초안 작성에 시간이 오래 걸린다.",
            current_workflow="품질 담당자가 QMS, 생산 이력, 검사 리포트를 조회하고 고객사 답변서를 작성한다.",
            weekly_hours=7,
            hourly_cost=45000,
            expected_effect=4,
            repeatability=4,
            document_dependency=4,
            decision_complexity=4,
            data_accessibility=3,
            tech_feasibility=4,
            user_acceptance=3,
            risk_score=3,
            implementation_cost_score=3,
            security_level="confidential",
            candidate_agent_name="고객 클레임 대응 Agent",
        ),
        BusinessProcess(
            company_id=company_id,
            department_id=departments["생산관리팀"].id,
            name="생산 회의록 Action Item 정리",
            target_user="생산관리자",
            problem="회의 후 담당자, 기한, 조치사항이 누락되거나 추적되지 않는 경우가 있다.",
            current_workflow="생산관리자가 회의록을 직접 정리하고 조치사항을 별도 엑셀이나 그룹웨어에 등록한다.",
            weekly_hours=5,
            hourly_cost=40000,
            expected_effect=3,
            repeatability=5,
            document_dependency=5,
            decision_complexity=2,
            data_accessibility=5,
            tech_feasibility=5,
            user_acceptance=4,
            risk_score=1,
            implementation_cost_score=1,
            security_level="internal",
            candidate_agent_name="생산 회의록 Action Item Agent",
        ),
        BusinessProcess(
            company_id=company_id,
            department_id=departments["구매자재팀"].id,
            name="구매 발주 조건 검토",
            target_user="구매 담당자",
            problem="발주 전 단가, 납기, 최소주문수량, 계약 조건 검토가 누락될 위험이 있다.",
            current_workflow="구매 담당자가 ERP와 계약 문서를 확인하고 팀장 승인을 받은 뒤 발주한다.",
            weekly_hours=7,
            hourly_cost=45000,
            expected_effect=4,
            repeatability=3,
            document_dependency=4,
            decision_complexity=4,
            data_accessibility=3,
            tech_feasibility=3,
            user_acceptance=3,
            risk_score=4,
            implementation_cost_score=3,
            security_level="restricted",
            candidate_agent_name="구매 발주 검토 Agent",
        ),
        BusinessProcess(
            company_id=company_id,
            department_id=departments["구매자재팀"].id,
            name="재고 부족 예측",
            target_user="물류/자재 담당자",
            problem="재고 부족과 과잉재고가 반복되며, 생산계획과 입출고 데이터를 함께 봐야 한다.",
            current_workflow="자재 담당자가 WMS, ERP, 생산계획 데이터를 확인하고 발주 필요 여부를 판단한다.",
            weekly_hours=9,
            hourly_cost=45000,
            expected_effect=5,
            repeatability=3,
            document_dependency=3,
            decision_complexity=4,
            data_accessibility=3,
            tech_feasibility=3,
            user_acceptance=3,
            risk_score=3,
            implementation_cost_score=4,
            security_level="confidential",
            candidate_agent_name="재고 부족 예측 및 발주 추천 Agent",
        ),
        BusinessProcess(
            company_id=company_id,
            department_id=departments["IT기획팀"].id,
            name="사내 IT 문의 대응",
            target_user="IT운영 담당자",
            problem="ERP, MES 사용 문의가 반복되어 IT운영자의 단순 응대 시간이 증가한다.",
            current_workflow="사용자가 그룹웨어나 메신저로 문의하면 IT 담당자가 매뉴얼을 찾아 답변한다.",
            weekly_hours=6,
            hourly_cost=40000,
            expected_effect=3,
            repeatability=5,
            document_dependency=5,
            decision_complexity=2,
            data_accessibility=5,
            tech_feasibility=5,
            user_acceptance=4,
            risk_score=1,
            implementation_cost_score=1,
            security_level="internal",
            candidate_agent_name="사내 IT 문의 대응 Agent",
        ),
        BusinessProcess(
            company_id=company_id,
            department_id=departments["IT기획팀"].id,
            name="AX 도입 우선순위 판단",
            target_user="IT기획팀, AX추진팀",
            problem="부서별 AI Agent 도입 요구가 증가하지만 어떤 업무부터 PoC를 추진해야 하는지 판단 기준이 부족하다.",
            current_workflow="IT기획 담당자가 부서 인터뷰, 시스템 현황, 비용 효과, 보안 위험을 수작업으로 비교한다.",
            weekly_hours=12,
            hourly_cost=50000,
            expected_effect=5,
            repeatability=4,
            document_dependency=5,
            decision_complexity=5,
            data_accessibility=3,
            tech_feasibility=4,
            user_acceptance=4,
            risk_score=3,
            implementation_cost_score=3,
            security_level="confidential",
            candidate_agent_name="AX Delivery Planner",
        ),
    ]

    db.add_all(processes)
    db.flush()
    return {process.name: process for process in processes}


def seed_documents(db, company_id: int, processes: dict[str, BusinessProcess]):
    """seed_documents 함수. 데모용 초기 데이터를 DB에 넣는 script. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    documents = [
        ProcessDocument(
            company_id=company_id,
            process_id=processes["SOP 검색"].id,
            title="SOP-MFG-001 작업표준서 검색 및 적용 절차",
            document_type="SOP",
            department="생산관리팀",
            security_level="internal",
            contains_sensitive_info=False,
            content=(
                "작업자는 생산 시작 전 해당 공정의 작업표준서를 확인해야 한다. "
                "현재 SOP 문서는 공유폴더, 그룹웨어, MES 첨부파일에 분산되어 있다. "
                "신입 작업자는 필요한 문서를 찾기 위해 선임자에게 문의하는 경우가 많으며, "
                "평균 검색 시간은 건당 8~12분이다. 문서 버전이 오래된 경우 최신 개정본 확인이 필요하다."
            ),
        ),
        ProcessDocument(
            company_id=company_id,
            process_id=processes["설비 고장 이력 검색"].id,
            title="MAINT-LOG-2026 설비 고장 및 조치 이력",
            document_type="Maintenance Log",
            department="설비정비팀",
            security_level="internal",
            contains_sensitive_info=False,
            content=(
                "2026년 3월 CNC-02 설비에서 스핀들 과열 경고가 발생했다. "
                "과거 유사 사례는 2025년 11월 CNC-04에서 발생했으며, 냉각팬 이상과 윤활유 부족이 원인이었다. "
                "정비 담당자는 CMMS와 엑셀 파일을 별도로 조회해야 하며, 유사 사례 검색에 평균 20분 이상 소요된다."
            ),
        ),
        ProcessDocument(
            company_id=company_id,
            process_id=processes["품질 불량 원인 분석"].id,
            title="QMS-DEFECT-2026 품질 불량 분석 보고서",
            document_type="Quality Report",
            department="품질관리팀",
            security_level="confidential",
            contains_sensitive_info=True,
            content=(
                "2026년 2분기 주요 불량 유형은 치수 편차, 납땜 불량, 표면 스크래치이다. "
                "치수 편차는 특정 라인의 공구 마모와 관련이 있었으며, 생산조건과 검사 결과를 함께 비교해야 한다. "
                "현재 품질 담당자는 QMS, MES, 검사 리포트를 수작업으로 비교한다. "
                "고객사별 품질 기준과 LOT 정보가 포함되므로 접근 권한 관리가 필요하다."
            ),
        ),
        ProcessDocument(
            company_id=company_id,
            process_id=processes["안전 점검 리포트 작성"].id,
            title="SAFE-CHECK-001 월간 안전점검 체크리스트",
            document_type="Safety Checklist",
            department="안전관리팀",
            security_level="internal",
            contains_sensitive_info=False,
            content=(
                "안전관리자는 매월 설비 보호커버, 비상정지 버튼, 통로 적재물, 보호구 착용 상태를 점검한다. "
                "점검 결과는 엑셀로 작성되며, 위험요인과 조치사항을 월간 보고서에 다시 정리해야 한다. "
                "반복 작성 시간이 길고 위험 항목 누락 가능성이 있다."
            ),
        ),
        ProcessDocument(
            company_id=company_id,
            process_id=processes["고객 클레임 대응"].id,
            title="VOC-CLIENT-2026 고객 클레임 대응 절차",
            document_type="VOC Procedure",
            department="품질관리팀",
            security_level="confidential",
            contains_sensitive_info=True,
            content=(
                "고객 클레임 접수 시 품질관리팀은 불량 유형, 생산 LOT, 검사 결과, 출하 이력을 확인해야 한다. "
                "고객사명과 계약 조건이 포함될 수 있으므로 외부 모델 전송은 제한된다. "
                "답변서는 품질팀 검토 후 영업 담당자와 관리자 승인을 받아 발송한다."
            ),
        ),
        ProcessDocument(
            company_id=company_id,
            process_id=processes["구매 발주 조건 검토"].id,
            title="PUR-ORDER-001 발주 검토 정책",
            document_type="Purchase Policy",
            department="구매자재팀",
            security_level="restricted",
            contains_sensitive_info=True,
            content=(
                "구매 발주 전 공급사 단가, 납기, 최소주문수량, 기존 계약 조건을 확인해야 한다. "
                "원가 정보와 공급사 계약 조건은 restricted 등급으로 분류된다. "
                "AI Agent가 발주를 자동 실행해서는 안 되며, 구매 담당자와 팀장 승인이 필요하다."
            ),
        ),
        ProcessDocument(
            company_id=company_id,
            process_id=processes["사내 IT 문의 대응"].id,
            title="IT-HELP-001 ERP/MES 사용 문의 처리 지침",
            document_type="IT Manual",
            department="IT기획팀",
            security_level="internal",
            contains_sensitive_info=False,
            content=(
                "ERP 비밀번호 초기화, MES 작업지시 조회, QMS 검사 결과 조회 문의가 반복적으로 발생한다. "
                "IT운영자는 매뉴얼을 검색해 답변하고 있으며, 단순 문의 대응 시간이 주당 6시간 이상 발생한다. "
                "FAQ와 매뉴얼 기반 질의응답 Agent 적용 가능성이 높다."
            ),
        ),
        ProcessDocument(
            company_id=company_id,
            process_id=processes["AX 도입 우선순위 판단"].id,
            title="AX-PLAN-001 제조 AX 과제 선정 기준",
            document_type="AX Planning Guide",
            department="IT기획팀",
            security_level="confidential",
            contains_sensitive_info=True,
            content=(
                "AI Agent PoC 후보는 기대효과, 데이터 접근성, 반복성, 구현 용이성, 현업 수용성, "
                "보안 및 거버넌스 위험, 추정 구현 비용을 기준으로 평가한다. "
                "위험도 4 이상 업무는 Human Review를 필수로 적용하고, 데이터 접근성 2 이하 업무는 데이터 정비를 선행한다. "
                "최종 PoC 착수 여부는 IT기획팀, 현업 부서장, 보안 담당자의 승인 후 결정한다."
            ),
        ),
    ]

    db.add_all(documents)
    db.flush()
    return documents


def seed_project(db, company_id: int):
    """seed_project 함수. 데모용 초기 데이터를 DB에 넣는 script. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    project = AnalysisProject(
        company_id=company_id,
        title="2026 제조기업 AX 전환 사전진단 프로젝트",
        status="created",
    )
    db.add(project)
    db.flush()
    return project


def run_seed(reset: bool = False) -> None:
    """run_seed 함수. 외부 API, graph, worker, 평가 루틴 같은 실행 단위를 호출하고 결과를 반환한다."""
    with SessionLocal() as db:
        if reset:
            delete_seed_data(db)

        company = seed_company(db)
        departments = seed_departments(db, company.id)
        seed_systems(db, company.id)
        processes = seed_processes(db, company.id, departments)
        seed_documents(db, company.id, processes)
        project = seed_project(db, company.id)

        db.commit()

        print("Seed data inserted successfully.")
        print(f"company_id={company.id}")
        print(f"project_id={project.id}")


def parse_args():
    """CLI 실행 인자를 정의하고 argparse Namespace로 변환한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing seed data before inserting new data.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_seed(reset=args.reset)