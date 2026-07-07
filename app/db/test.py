# app/tools/check_docx_generator.py

from __future__ import annotations

from app.tools.docx_generator import generate_docx_report


def main() -> None:
    report_data = {
        "title": "Multi-Agent 기반 제조기업 AX 전환 업무 프로세스 진단 및 AI Agent 도입 우선순위 추천 Agent 설계",
        "author": "오재식",
        "company_name": "Hanbit Precision Manufacturing",
        "mvp_agent": "AX Delivery Planner",
        "date": "2026-07",
        "sections": [
            {
                "heading": "1. 주제 정의 및 선정 배경",
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": (
                            "본 과제는 제조기업의 IT기획팀과 AX 추진 담당자를 위해 "
                            "현업 업무 프로세스와 데이터 보유 현황을 분석하고, "
                            "AI Agent 도입 후보의 우선순위를 추천하는 AX Delivery Planner를 설계한다."
                        ),
                    },
                    {
                        "type": "paragraph",
                        "text": (
                            "제조기업은 생산관리, 품질관리, 설비정비, 안전관리, 구매자재 등 "
                            "다양한 업무 영역에서 AI Agent 도입 가능성을 가지고 있다. "
                            "그러나 예산, 데이터 접근성, 보안 위험, 기술 난이도 때문에 "
                            "모든 업무를 동시에 PoC로 추진하기 어렵다."
                        ),
                    },
                ],
            },
            {
                "heading": "2. 우선순위 분석 결과",
                "blocks": [
                    {
                        "type": "table",
                        "headers": ["순위", "후보 Agent", "점수", "상태", "예상 절감률"],
                        "rows": [
                            [1, "SOP 질의응답 Agent", 3.5, "recommended", "55.0%"],
                            [2, "생산 회의록 Action Item Agent", 3.45, "recommended", "51.0%"],
                            [3, "AX Delivery Planner", 3.4, "recommended", "45.0%"],
                        ],
                    },
                    {
                        "type": "paragraph",
                        "text": (
                            "위 표는 개별 업무 PoC 후보의 우선순위 예시이다. "
                            "최종 MVP는 특정 업무 Agent가 아니라, 여러 후보를 비교하고 "
                            "PoC 우선순위를 추천하는 AX Delivery Planner이다."
                        ),
                    },
                ],
            },
        ],
        "references": [
            "python-docx 1.2.0 Documentation, Quickstart.",
            "LangGraph Documentation, Graph API.",
            "LangChain Documentation, OpenAIEmbeddings.",
        ],
    }

    output_path = generate_docx_report(
        report_data=report_data,
        output_path="outputs/test_report.docx",
    )

    print(f"DOCX generated: {output_path}")


if __name__ == "__main__":
    main()