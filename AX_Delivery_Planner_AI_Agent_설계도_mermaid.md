# AX Delivery Planner AI Agent 설계도

> Multi-Agent 기반 제조기업 AX 업무 진단 및 AI Agent 도입 우선순위 추천 시스템  
> 제출용 구성: **전체 시스템 아키텍처 다이어그램 + 업무 흐름도**

---

## 1. 전체 시스템 아키텍처 다이어그램

```mermaid
flowchart TB
    %% =========================================================
    %% AX Delivery Planner - Overall System Architecture
    %% =========================================================

    %% ---------- User Layer ----------
    subgraph U["1. 사용자 및 인터페이스 계층"]
        U1["IT기획팀"]
        U2["AX/DX 추진팀"]
        U3["현업 부서장"]
        U4["보안·준법 담당자"]
        U5["경영진"]

        UI1["Web UI / CLI<br/>웹 브라우저·터미널 접근"]
        UI2["FastAPI API<br/>프로그램 연동 및 자동화"]
        UI3["Human Review UI<br/>검토·승인·피드백"]
    end

    U1 --> UI1
    U2 --> UI1
    U2 --> UI2
    U3 --> UI3
    U4 --> UI3
    U5 --> UI3

    %% ---------- Supervisor Layer ----------
    subgraph S["2. Supervisor Orchestration Layer"]
        SUP["AX Delivery Supervisor Agent<br/><br/>workflow orchestration<br/>task delegation<br/>state management<br/>replan routing"]
    end

    UI1 --> SUP
    UI2 --> SUP
    UI3 --> SUP

    %% ---------- Expert Agent Layer ----------
    subgraph A["3. Expert Agent Layer"]
        A1["Context & Evidence Agent<br/><br/>역할: 프로젝트 정보 로드·문서 검색·근거 수집<br/>도구: load_project_data, retrieve_context<br/>산출물: context_evidence_package"]

        A2["Process Diagnosis Agent<br/><br/>역할: 업무 프로세스 분석·데이터 준비도 평가·자동화 가능성 진단<br/>도구: process_analyzer, data_readiness, automation_feasibility<br/>산출물: process_diagnosis_package"]

        A3["Governance & Compliance Agent<br/><br/>역할: 보안·규제·책임 리스크 평가<br/>도구: risk_governance, compliance_assessment<br/>산출물: governance_package"]

        A4["Business Case Agent<br/><br/>역할: ROI 및 비용 추정·우선순위 점수화<br/>도구: roi_cost, priority_ranking<br/>산출물: business_case_package"]

        A5["Evaluation & Critic Agent<br/><br/>역할: 결과 검증·근거 품질 평가·재계획 판단<br/>도구: agent_evaluator, llm_critic<br/>산출물: evaluation_package"]

        A6["Delivery Orchestration Agent<br/><br/>역할: Human Review 반영·PoC 계획서 및 보고서 생성<br/>도구: human_review, poc_delivery_planner, report_writer, docx_generator<br/>산출물: delivery_package"]
    end

    SUP --> A1
    SUP --> A2
    SUP --> A3
    SUP --> A4
    SUP --> A5
    SUP --> A6

    A1 --> A2
    A1 --> A3
    A2 --> A4
    A3 --> A4
    A4 --> A5
    A5 --> A6

    %% ---------- Data & RAG Layer ----------
    subgraph D["4. Data & RAG Layer"]
        D1[("PostgreSQL<br/>관계형 데이터 저장소")]
        D2[("pgvector<br/>벡터 임베딩 저장소")]
        D3["공식/내부 문서<br/>사내 정책·가이드·표준·프로세스·템플릿"]
        D4["Evidence Items / Sources<br/>수집된 근거·보고서·데이터 출처"]
    end

    D1 <--> A1
    D2 <--> A1
    D3 --> A1
    A1 --> D4
    D4 --> A5
    D4 -.근거 참조.-> A4

    %% ---------- Governance Layer ----------
    subgraph G["5. Governance & Control Layer"]
        G1["RBAC<br/>역할 기반 접근 제어"]
        G2["PII/기밀 마스킹<br/>개인정보·기밀 데이터 보호"]
        G3["Tool Allowlist<br/>허용된 도구만 실행"]
        G4["Audit Log<br/>모든 활동 추적 및 기록"]
        G5["Human-in-the-loop Review<br/>최종 검토 및 승인 프로세스"]
    end

    G1 -.통제.-> A1
    G1 -.통제.-> A2
    G1 -.통제.-> A3
    G2 -.통제.-> A1
    G2 -.통제.-> A6
    G3 -.통제.-> A2
    G3 -.통제.-> A4
    G4 -.기록.-> SUP
    G4 -.기록.-> A5
    G5 -.승인.-> A6
    UI3 --> G5

    %% ---------- Output Layer ----------
    subgraph O["6. 최종 산출물"]
        O1["AI Agent 후보 랭킹<br/>우선순위 점수 및 상세 근거 포함"]
        O2["MVP 추천 결과<br/>단계별 MVP 범위 및 기대효과"]
        O3["PoC 실행 계획<br/>일정·범위·자원·리스크·성공 지표 포함"]
        O4["Workflow State / Agent Trace<br/>워크플로 상태·실행 로그·에이전트 트레이스"]
        O5["DOCX 보고서<br/>경영진 보고용 종합 보고서"]
    end

    A6 --> O1
    A6 --> O2
    A6 --> O3
    A6 --> O4
    A6 --> O5

    %% ---------- Value Callout ----------
    V["핵심 가치<br/>데이터·비용·위험·수용성을 함께 평가하여<br/>제조기업 AX 전환의 PoC 우선순위를 결정"]
    O2 --> V

    %% ---------- Styles ----------
    classDef navy fill:#0B1F3A,stroke:#0B1F3A,color:#FFFFFF,stroke-width:1px;
    classDef teal fill:#E6FAF8,stroke:#00A6A6,color:#0B1F3A,stroke-width:1px;
    classDef light fill:#FFFFFF,stroke:#B8C7D9,color:#0B1F3A,stroke-width:1px;
    classDef green fill:#E9F8EF,stroke:#2EAD68,color:#0B1F3A,stroke-width:1px;
    classDef yellow fill:#FFF6D8,stroke:#D7A900,color:#0B1F3A,stroke-width:1px;
    classDef risk fill:#FFF0F0,stroke:#D9534F,color:#0B1F3A,stroke-width:1px;

    class SUP navy;
    class A1,A2,A3,A4,A5,A6 teal;
    class D1,D2,D3,D4 light;
    class G1,G2,G3,G4,G5 green;
    class O1,O2,O3,O4,O5 light;
    class V yellow;
```

---

## 2. AI Agent 업무 흐름도

```mermaid
flowchart TD
    %% =========================================================
    %% AX Delivery Planner - Business Workflow Diagram
    %% =========================================================

    %% ---------- Input Stage ----------
    subgraph I["A. 입력 단계"]
        I1["업무 설명서"]
        I2["SOP"]
        I3["정비 이력"]
        I4["품질 보고서"]
        I5["회의록"]
        I6["ERP / MES / QMS / CMMS 현황표"]
        I7["보안 등급표"]
        IP["Input Package<br/>문서 + 시스템 현황 + 보안·비용 조건"]
    end

    I1 --> IP
    I2 --> IP
    I3 --> IP
    I4 --> IP
    I5 --> IP
    I6 --> IP
    I7 --> IP

    %% ---------- Supervisor Start ----------
    subgraph S["B. Supervisor 시작"]
        SUP["AX Delivery Supervisor Agent<br/><br/>task assignment<br/>agent sequencing<br/>replan decision<br/>state tracking"]
    end

    IP --> SUP

    %% ---------- Agent Execution Unit Note ----------
    UNIT["공통 Agent 실행 단위<br/>command prompt → assigned tools → reflection prompt → package → handoff"]

    %% ---------- Stage 1 ----------
    subgraph ST1["1. Context & Evidence Agent"]
        C1["command prompt"]
        C2["tools<br/>load_project_data<br/>retrieve_context"]
        C3["reflection prompt"]
        C4["context_evidence_package"]
    end

    SUP --> C1
    C1 --> C2 --> C3 --> C4

    %% ---------- Stage 2 ----------
    subgraph ST2["2. Process Diagnosis Agent"]
        P1["command prompt"]
        P2["tools<br/>process_analyzer<br/>data_readiness<br/>automation_feasibility"]
        P3["reflection prompt"]
        P4["process_diagnosis_package"]
    end

    C4 --> P1
    P1 --> P2 --> P3 --> P4

    %% ---------- Stage 3 ----------
    subgraph ST3["3. Governance & Compliance Agent"]
        G1["command prompt"]
        G2["tools<br/>risk_governance<br/>compliance_assessment"]
        G3["reflection prompt"]
        G4["governance_package"]
    end

    C4 --> G1
    G1 --> G2 --> G3 --> G4

    %% ---------- Stage 4 ----------
    subgraph ST4["4. Business Case Agent"]
        B1["command prompt"]
        B2["tools<br/>roi_cost<br/>priority_ranking"]
        B3["reflection prompt"]
        B4["business_case_package"]
    end

    P4 --> B1
    G4 --> B1
    B1 --> B2 --> B3 --> B4

    %% ---------- Stage 5 ----------
    subgraph ST5["5. Evaluation & Critic Agent"]
        E1["command prompt"]
        E2["tools<br/>agent_evaluator<br/>llm_critic"]
        E3["reflection prompt"]
        E4["evaluation_package"]
    end

    B4 --> E1
    E1 --> E2 --> E3 --> E4

    %% ---------- Decision ----------
    DEC{"근거 충분 / 검증 통과?"}
    E4 --> DEC

    %% ---------- Replan Loop ----------
    RP["Agent Replan Task<br/>추가 근거 수집 및 재평가 요청"]
    DEC -- "No<br/>근거 부족·품질 미흡" --> RP
    RP -.Replan Loop.-> C1

    %% ---------- Human Review ----------
    subgraph HR["6. Human Review Gate"]
        H1["approve"]
        H2["edit"]
        H3["reject"]
        H4["comment"]
        H5["audit log"]
        HRG["고위험 항목·민감정보·우선순위 수정 검토"]
    end

    DEC -- "Yes<br/>검증 완료 또는 사람 검토 필요" --> HRG
    HRG --> H1
    HRG --> H2
    HRG --> H3
    HRG --> H4
    H1 --> H5
    H2 --> H5
    H3 --> H5
    H4 --> H5

    %% ---------- Stage 7 Delivery ----------
    subgraph ST7["7. Delivery Orchestration Agent"]
        D1["command prompt"]
        D2["tools<br/>poc_delivery_planner<br/>report_writer<br/>docx_generator"]
        D3["reflection prompt"]
        D4["delivery_package"]
    end

    H5 --> D1
    D1 --> D2 --> D3 --> D4

    %% ---------- Outputs ----------
    subgraph O["D. 최종 산출물"]
        O1["후보 Agent 10개 목록"]
        O2["우선순위 점수표"]
        O3["MVP 추천"]
        O4["PoC 계획서"]
        O5["workflow_state_real.json"]
        O6["AX_Delivery_Planner_Report_1.docx"]
    end

    D4 --> O1
    D4 --> O2
    D4 --> O3
    D4 --> O4
    D4 --> O5
    D4 --> O6

    %% ---------- Execution Rules ----------
    subgraph R["실행 규칙"]
        R1["각 Agent는 자신의 도구만 호출"]
        R2["모든 handoff는 package 단위 전달"]
        R3["모든 주요 판단은 audit log 기록"]
        R4["Human Review 후 최종 배포"]
    end

    UNIT -.적용.-> C1
    UNIT -.적용.-> P1
    UNIT -.적용.-> G1
    UNIT -.적용.-> B1
    UNIT -.적용.-> E1
    UNIT -.적용.-> D1

    R1 -.통제.-> ST1
    R2 -.통제.-> ST4
    R3 -.통제.-> HR
    R4 -.통제.-> ST7

    %% ---------- Prototype Metrics ----------
    subgraph M["실제 프로토타입 실행 결과"]
        M1["Agent stage: 7개"]
        M2["agent_llm_calls: 14건"]
        M3["agent_commands: 14건"]
        M4["agent_supervisor_steps: 7건"]
        M5["agent_handoffs: 9건"]
        M6["agent_loop_requests: 3건"]
        M7["errors: 0건"]
    end

    O5 --> M

    %% ---------- Styles ----------
    classDef navy fill:#0B1F3A,stroke:#0B1F3A,color:#FFFFFF,stroke-width:1px;
    classDef teal fill:#E6FAF8,stroke:#00A6A6,color:#0B1F3A,stroke-width:1px;
    classDef green fill:#E9F8EF,stroke:#2EAD68,color:#0B1F3A,stroke-width:1px;
    classDef orange fill:#FFF3E0,stroke:#F4A261,color:#0B1F3A,stroke-width:1px;
    classDef yellow fill:#FFF6D8,stroke:#D7A900,color:#0B1F3A,stroke-width:1px;
    classDef light fill:#FFFFFF,stroke:#B8C7D9,color:#0B1F3A,stroke-width:1px;

    class SUP navy;
    class IP,UNIT yellow;
    class C1,C2,C3,C4,P1,P2,P3,P4,G1,G2,G3,G4,B1,B2,B3,B4,E1,E2,E3,E4,D1,D2,D3,D4 teal;
    class DEC orange;
    class RP orange;
    class HRG,H1,H2,H3,H4,H5 green;
    class O1,O2,O3,O4,O5,O6 light;
    class R1,R2,R3,R4 green;
    class M1,M2,M3,M4,M5,M6,M7 light;
```

---

## 3. 제출용 사용 방법

Mermaid를 지원하는 Markdown 뷰어에서 열면 위 두 다이어그램이 자동 렌더링된다.

추천 사용 방식은 다음과 같다.

1. `VS Code`에서 Markdown Preview Mermaid Support 확장 설치
2. 이 `.md` 파일 열기
3. Mermaid Preview 또는 Markdown Preview로 확인
4. 필요 시 PDF로 인쇄 또는 캡처하여 발표자료/보고서에 삽입
