# app/agents/model_router.py
"""Supervisor가 LLM 호출별 모델을 선택하는 비용/성능 라우터다.

이 파일은 OpenAI, Anthropic, vLLM 후보를 같은 형식의 `ModelProfile`로 만든 뒤,
입력 자료량, 예상 출력량, 업무 복잡도, 예상 처리 시간, 모델 품질, context window,
가격을 하나의 수식으로 비교한다.

정책 요약:
- Supervisor Agent는 항상 설정된 상위 모델을 우선 사용한다.
- 나머지 Expert Agent command/reflection/tool LLM은 가격 대비 효율 수식으로 고른다.
- timeout retry 시에는 이전보다 더 강한 모델 또는 다른 고품질 provider로 상향한다.
- 모든 선택 근거와 비용 계산은 `agent_model_decisions`에 남긴다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from app.core.config import get_settings


# Supervisor Agent는 전체 흐름의 위임, 모델 선택, 품질 통제를 담당하는
# 최상위 역할로 취급한다. 실제 LangGraph에는 별도 Supervisor LLM 노드가
# 없지만, 이 ID를 기준으로 "항상 상위 모델" 정책을 적용하고 trace에 남긴다.
SUPERVISOR_AGENT_ID = "ax_delivery_supervisor_agent"


# Agent별 기본 난이도 계수다. 같은 입력량이어도 규제/평가/보고서 생성은
# 단순 조회보다 판단 위험이 크므로 더 높은 모델 품질을 요구한다.
AGENT_COMPLEXITY_WEIGHT = {
    "company_onboarding_agent": 0.70,
    "context_evidence_agent": 0.58,
    "process_diagnosis_agent": 0.64,
    "governance_compliance_agent": 0.82,
    "business_case_agent": 0.72,
    "evaluation_critic_agent": 0.86,
    "delivery_orchestration_agent": 0.78,
    SUPERVISOR_AGENT_ID: 1.00,
}


# 호출 종류별 난이도 보정값이다. command/reflection은 비교적 짧은 JSON
# 계획이지만, report_writer와 llm_critic은 실제 판단/문장화 품질 영향이 크다.
CALL_KIND_COMPLEXITY_BONUS = {
    "agent_command": 0.04,
    "agent_reflection": 0.06,
    "process_discovery_llm": 0.10,
    "tool_llm_critic": 0.12,
    "report_writer": 0.15,
    "supervisor_delegation": 0.20,
    "supervisor_model_policy": 0.20,
}


# 작업량 계산 시 의미 있는 state key만 본다. 전체 state를 무작정 직렬화하면
# 감사 로그나 중복 trace가 모델 선택을 과하게 키울 수 있기 때문이다.
WORKLOAD_STATE_KEYS = [
    "company_profile",
    "official_sources",
    "business_processes",
    "documents",
    "retrieved_contexts",
    "retrieval_query_plan",
    "evidence_items",
    "used_sources",
    "process_analysis",
    "data_readiness",
    "automation_feasibility",
    "risk_governance",
    "compliance_assessment",
    "roi_cost",
    "priority_ranking",
    "agent_evaluation",
    "replan_request",
    "poc_plan",
    "report_data",
]


@dataclass(frozen=True)
class WorkloadMetrics:
    """모델 선택 수식에 들어가는 작업량 지표."""

    input_chars: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    process_count: int
    document_count: int
    evidence_count: int
    source_count: int
    priority_candidate_count: int
    data_volume_score: float
    complexity_score: float
    estimated_seconds: float
    time_pressure_score: float
    required_quality_score: float

    def to_dict(self) -> dict[str, Any]:
        """dataclass/value object를 JSON 직렬화 가능한 dict로 변환한다."""
        return asdict(self)


@dataclass(frozen=True)
class ModelProfile:
    """라우터가 비교하는 모델 후보의 정규화된 성능/가격 정보."""

    provider: str
    model: str
    tier: str
    quality_score: float
    speed_score: float
    context_window_tokens: int
    input_cost_per_million: float
    output_cost_per_million: float
    available: bool
    unavailable_reason: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """workflow_state에 남겨도 되는 모델 후보 정보를 반환한다."""

        # API key 같은 비밀값은 절대 trace에 넣지 않는다. 모델 선택 근거에
        # 필요한 공개 메타데이터만 남긴다.
        return {
            "provider": self.provider,
            "model": self.model,
            "tier": self.tier,
            "quality_score": self.quality_score,
            "speed_score": self.speed_score,
            "context_window_tokens": self.context_window_tokens,
            "input_cost_per_million": self.input_cost_per_million,
            "output_cost_per_million": self.output_cost_per_million,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
        }


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    """점수 계산 값이 0~1 범위를 벗어나지 않도록 제한한다."""

    return max(lower, min(upper, value))


def compact_json_size(value: Any, max_chars: int = 300_000) -> int:
    """state 일부를 JSON으로 바꾼 뒤 대략적인 문자 수를 구한다.

    실제 tokenizer를 매번 돌리면 모델 선택 자체가 비싸지고 느려진다. 그래서
    운영 라우터에서는 보통 문자 수 기반의 근사치를 쓰고, 여기서는 한글/영문
    혼합 문서 기준으로 1 token ~= 4 chars라는 보수적 근사를 사용한다.
    """

    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        text = str(value)
    return min(len(text), max_chars)


def estimate_tokens_from_chars(char_count: int) -> int:
    """문자 수를 LLM 비용 산정용 token 수로 근사한다."""

    # 너무 작은 입력도 모델 호출에는 system/user prompt가 붙기 때문에
    # 최소 128 token으로 잡아 과소평가를 피한다.
    return max(128, int(char_count / 4))


def count_items(value: Any) -> int:
    """list/dict 계열 state 값의 크기만 안전하게 센다."""

    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    return 0


def estimate_workload(
    *,
    agent_id: str,
    stage_name: str,
    call_kind: str,
    state: dict[str, Any],
    target_seconds: float,
) -> WorkloadMetrics:
    """자료량, 처리 대상 수, 예상 시간으로 난이도를 정량화한다.

    수식 요약:
    - input_tokens = 선택된 state key들의 JSON 문자 수 / 4
    - output_tokens = 기본 출력량 + 후보/근거/문서 개수에 따른 가산치
    - data_volume_score = input token이 24k에 가까울수록 1에 가까움
    - complexity_score = Agent 기본 난이도 + 호출 종류 보정 + replan/위험 신호
    - estimated_seconds = token 처리량과 복잡도 기반의 추정 실행 시간
    - required_quality_score = 데이터량/복잡도/시간압박을 섞은 요구 품질 점수
    """

    relevant_state = {key: state.get(key) for key in WORKLOAD_STATE_KEYS if key in state}
    input_chars = compact_json_size(relevant_state)
    estimated_input_tokens = estimate_tokens_from_chars(input_chars)

    process_count = count_items(state.get("business_processes"))
    document_count = count_items(state.get("documents"))
    evidence_count = count_items(state.get("evidence_items"))
    source_count = count_items(state.get("used_sources") or state.get("official_sources"))
    priority_candidate_count = count_items((state.get("priority_ranking") or {}).get("items"))

    base_output_tokens = 700
    if call_kind == "report_writer":
        base_output_tokens = 3_000
    elif call_kind == "tool_llm_critic":
        base_output_tokens = 900
    elif call_kind == "process_discovery_llm":
        base_output_tokens = 1_800

    estimated_output_tokens = int(
        base_output_tokens
        + process_count * 90
        + priority_candidate_count * 120
        + min(evidence_count, 40) * 35
        + min(document_count, 20) * 30
    )

    data_volume_score = clamp(estimated_input_tokens / 24_000)
    base_complexity = AGENT_COMPLEXITY_WEIGHT.get(agent_id, 0.65)
    call_bonus = CALL_KIND_COMPLEXITY_BONUS.get(call_kind, 0.0)
    replan_bonus = 0.08 if state.get("replan_request") else 0.0
    risk_bonus = 0.06 if state.get("risk_governance") or state.get("compliance_assessment") else 0.0
    complexity_score = clamp(base_complexity + call_bonus + replan_bonus + risk_bonus)

    # 시간 추정은 "입력 읽기 + 출력 생성 + 판단 복잡도"로 나눈다.
    # 이 값은 특정 공급자의 실제 latency가 아니라 라우팅을 위한 상대 지표다.
    estimated_seconds = round(
        (estimated_input_tokens / 1_000) * 0.80
        + (estimated_output_tokens / 1_000) * 3.20
        + complexity_score * 8.0,
        3,
    )
    safe_target_seconds = max(1.0, float(target_seconds or 45.0))
    time_pressure_score = clamp(estimated_seconds / safe_target_seconds)

    required_quality_score = clamp(
        0.42
        + data_volume_score * 0.22
        + complexity_score * 0.28
        + time_pressure_score * 0.08,
        lower=0.45,
        upper=0.94,
    )

    return WorkloadMetrics(
        input_chars=input_chars,
        estimated_input_tokens=estimated_input_tokens,
        estimated_output_tokens=estimated_output_tokens,
        process_count=process_count,
        document_count=document_count,
        evidence_count=evidence_count,
        source_count=source_count,
        priority_candidate_count=priority_candidate_count,
        data_volume_score=round(data_volume_score, 4),
        complexity_score=round(complexity_score, 4),
        estimated_seconds=estimated_seconds,
        time_pressure_score=round(time_pressure_score, 4),
        required_quality_score=round(required_quality_score, 4),
    )


def has_value(value: str | None) -> bool:
    """API key나 모델명처럼 빈 문자열이면 없는 값으로 봐야 하는 설정 검사."""

    return bool(str(value or "").strip())


def safe_float(value: Any, default: float) -> float:
    """env JSON 후보의 숫자 필드를 안전하게 float로 변환한다."""

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int) -> int:
    """env JSON 후보의 숫자 필드를 안전하게 int로 변환한다."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_openai_extra_model_profiles(openai_available: bool) -> list[ModelProfile]:
    """`.env`의 추가 GPT 후보 JSON을 ModelProfile 목록으로 변환한다.

    기본 `OPENAI_FAST/BALANCED/HIGH_MODEL` 3종 외에도 더 저렴한 GPT 계열 모델을
    후보에 넣고 싶을 때 사용한다. 예: mini/nano 등 접근 가능한 모델을 가격표와
    품질 점수로 등록하면 Supervisor 외 Agent들이 같은 비용/성능 수식으로 비교한다.
    """

    settings = get_settings()
    raw_json = str(settings.openai_extra_model_profiles_json or "").strip()
    if not raw_json:
        return []

    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return []

    if isinstance(payload, dict):
        payload = payload.get("models", [])
    if not isinstance(payload, list):
        return []

    profiles: list[ModelProfile] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        model_name = str(item.get("model") or "").strip()
        if not model_name:
            continue
        profiles.append(
            ModelProfile(
                provider="openai",
                model=model_name,
                tier=str(item.get("tier") or "custom").strip() or "custom",
                quality_score=clamp(safe_float(item.get("quality_score"), 0.72)),
                speed_score=clamp(safe_float(item.get("speed_score"), 0.86)),
                context_window_tokens=safe_int(item.get("context_window_tokens"), 128_000),
                input_cost_per_million=max(0.0, safe_float(item.get("input_cost_per_million"), 1.0)),
                output_cost_per_million=max(0.0, safe_float(item.get("output_cost_per_million"), 4.0)),
                available=openai_available,
                unavailable_reason=None if openai_available else "OPENAI_API_KEY missing or MODEL_ROUTER_ENABLE_OPENAI=false",
            )
        )
    return profiles


def build_model_profiles() -> list[ModelProfile]:
    """환경설정과 API key 유무를 반영해 모델 후보군을 만든다.

    vLLM은 로컬 endpoint라 API key가 없을 수 있으므로 enable flag만 본다.
    OpenAI/Anthropic은 key와 enable flag가 모두 있어야 available로 표시한다.
    unavailable 후보도 trace용으로 남길 수 있게 profile에는 포함한다.
    """

    settings = get_settings()
    openai_available = has_value(settings.openai_api_key) and settings.model_router_enable_openai
    anthropic_available = has_value(settings.anthropic_api_key) and settings.model_router_enable_anthropic
    vllm_available = settings.model_router_enable_vllm

    # 여기 적힌 품질/속도 점수는 절대 성능 benchmark가 아니라 "라우터가 같은
    # 단위로 비교하기 위한 상대 점수"다. 실제 가격이나 모델명이 바뀌면 .env의
    # cost/profile 설정을 바꾸고, 이 기본값은 로컬 개발의 기준표로 유지한다.
    profiles = [
        ModelProfile(
            provider="vllm",
            model=settings.vllm_model,
            tier="local",
            quality_score=clamp(settings.vllm_quality_score),
            speed_score=clamp(settings.vllm_speed_score),
            context_window_tokens=settings.vllm_context_window_tokens,
            input_cost_per_million=settings.vllm_input_cost_per_million,
            output_cost_per_million=settings.vllm_output_cost_per_million,
            available=vllm_available,
            unavailable_reason=None if vllm_available else "MODEL_ROUTER_ENABLE_VLLM=false",
        ),
        ModelProfile(
            provider="openai",
            model=settings.openai_fast_model,
            tier="fast",
            quality_score=0.82,
            speed_score=0.88,
            context_window_tokens=1_050_000,
            input_cost_per_million=settings.openai_fast_input_cost_per_million,
            output_cost_per_million=settings.openai_fast_output_cost_per_million,
            available=openai_available,
            unavailable_reason=None if openai_available else "OPENAI_API_KEY missing or MODEL_ROUTER_ENABLE_OPENAI=false",
        ),
        ModelProfile(
            provider="openai",
            model=settings.openai_balanced_model,
            tier="balanced",
            quality_score=0.91,
            speed_score=0.72,
            context_window_tokens=1_050_000,
            input_cost_per_million=settings.openai_balanced_input_cost_per_million,
            output_cost_per_million=settings.openai_balanced_output_cost_per_million,
            available=openai_available,
            unavailable_reason=None if openai_available else "OPENAI_API_KEY missing or MODEL_ROUTER_ENABLE_OPENAI=false",
        ),
        ModelProfile(
            provider="openai",
            model=settings.openai_high_model,
            tier="high",
            quality_score=0.97,
            speed_score=0.58,
            context_window_tokens=1_050_000,
            input_cost_per_million=settings.openai_high_input_cost_per_million,
            output_cost_per_million=settings.openai_high_output_cost_per_million,
            available=openai_available,
            unavailable_reason=None if openai_available else "OPENAI_API_KEY missing or MODEL_ROUTER_ENABLE_OPENAI=false",
        ),
        *parse_openai_extra_model_profiles(openai_available),
        ModelProfile(
            provider="anthropic",
            model=settings.anthropic_fast_model,
            tier="fast",
            quality_score=0.76,
            speed_score=0.78,
            context_window_tokens=200_000,
            input_cost_per_million=settings.anthropic_fast_input_cost_per_million,
            output_cost_per_million=settings.anthropic_fast_output_cost_per_million,
            available=anthropic_available,
            unavailable_reason=None if anthropic_available else "ANTHROPIC_API_KEY missing or MODEL_ROUTER_ENABLE_ANTHROPIC=false",
        ),
        ModelProfile(
            provider="anthropic",
            model=settings.anthropic_high_model,
            tier="high",
            quality_score=0.90,
            speed_score=0.60,
            context_window_tokens=200_000,
            input_cost_per_million=settings.anthropic_high_input_cost_per_million,
            output_cost_per_million=settings.anthropic_high_output_cost_per_million,
            available=anthropic_available,
            unavailable_reason=None if anthropic_available else "ANTHROPIC_API_KEY missing or MODEL_ROUTER_ENABLE_ANTHROPIC=false",
        ),
    ]

    # 같은 provider/model이 중복 등록되면 앞쪽 기본 후보를 우선한다.
    deduped: list[ModelProfile] = []
    seen: set[tuple[str, str]] = set()
    for profile in profiles:
        key = (profile.provider, profile.model)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(profile)
    return deduped


def estimate_model_cost_breakdown(profile: ModelProfile, metrics: WorkloadMetrics) -> dict[str, Any]:
    """모델 비용 산식을 trace에 남길 수 있게 입력/출력 비용을 분리한다."""

    input_cost = (metrics.estimated_input_tokens / 1_000_000) * profile.input_cost_per_million
    output_cost = (metrics.estimated_output_tokens / 1_000_000) * profile.output_cost_per_million
    total_cost = input_cost + output_cost
    return {
        "formula": "(input_tokens / 1_000_000 * input_cost_per_million) + (output_tokens / 1_000_000 * output_cost_per_million)",
        "estimated_input_tokens": metrics.estimated_input_tokens,
        "estimated_output_tokens": metrics.estimated_output_tokens,
        "input_cost_per_million": profile.input_cost_per_million,
        "output_cost_per_million": profile.output_cost_per_million,
        "input_cost_usd": round(input_cost, 6),
        "output_cost_usd": round(output_cost, 6),
        "total_cost_usd": round(total_cost, 6),
    }


def estimate_model_cost(profile: ModelProfile, metrics: WorkloadMetrics) -> float:
    """후보 모델의 총 예상 비용만 float로 반환한다."""

    return float(estimate_model_cost_breakdown(profile, metrics)["total_cost_usd"])


def score_model(profile: ModelProfile, metrics: WorkloadMetrics, max_candidate_cost: float, cost_sensitivity: float) -> dict[str, Any]:
    """모델별 가격 대비 효율 점수를 계산한다.

    최종 점수:
    utility
      = 품질 50% + 속도 20% + context 적합도 20% + 안정성 10%
    penalty
      = 비용 패널티 + 품질 부족 패널티 + context 부족 패널티 + 시간 초과 패널티
    score = utility - penalty
    """

    # context_fit은 hard filter와 scoring 양쪽에 모두 쓰인다. context window를
    # 넘는 모델을 완전히 배제하지는 않지만, 점수에서 강하게 불리하게 만들어
    # 극단적인 fallback 상황 외에는 선택되지 않게 한다.
    total_tokens = metrics.estimated_input_tokens + metrics.estimated_output_tokens
    context_fit = 1.0 if total_tokens <= profile.context_window_tokens else 0.15
    reliability = 0.86 if profile.provider == "vllm" else 0.92
    estimated_cost = estimate_model_cost(profile, metrics)
    normalized_cost = estimated_cost / max(max_candidate_cost, 0.000001)

    model_seconds = metrics.estimated_seconds / max(profile.speed_score, 0.20)
    time_overrun_ratio = max(0.0, model_seconds - metrics.estimated_seconds) / max(metrics.estimated_seconds, 1.0)

    quality_gap = max(0.0, metrics.required_quality_score - profile.quality_score)
    context_gap = 0.0 if context_fit >= 1.0 else 0.35

    utility = (
        profile.quality_score * 0.50
        + profile.speed_score * 0.20
        + context_fit * 0.20
        + reliability * 0.10
    )
    penalty = (
        clamp(cost_sensitivity) * normalized_cost
        + quality_gap * 1.35
        + context_gap
        + min(time_overrun_ratio, 1.0) * 0.12
    )
    score = round(utility - penalty, 6)

    return {
        "provider": profile.provider,
        "model": profile.model,
        "tier": profile.tier,
        "score": score,
        "utility": round(utility, 6),
        "penalty": round(penalty, 6),
        "estimated_cost_usd": estimated_cost,
        "cost_calculation": estimate_model_cost_breakdown(profile, metrics),
        "normalized_cost": round(normalized_cost, 6),
        "context_fit": round(context_fit, 4),
        "quality_gap": round(quality_gap, 4),
        "estimated_model_seconds": round(model_seconds, 3),
        "profile": profile.to_public_dict(),
    }


def choose_supervisor_profile(profiles: list[ModelProfile]) -> tuple[ModelProfile, str]:
    """Supervisor는 수식 최적화 대신 상위 모델 고정 정책을 우선 적용한다.

    Supervisor는 하위 Agent를 통제하고 사람 승인 경계를 판단하는 역할이라,
    비용 최적화보다 안정적인 reasoning 품질이 우선이다. 그래서 `.env`의
    `SUPERVISOR_MODEL_PROVIDER`와 `SUPERVISOR_MODEL_NAME`을 먼저 찾고,
    없으면 같은 provider 최고 품질, 그것도 없으면 전체 최고 품질로 대체한다.
    """

    settings = get_settings()
    available_profiles = [profile for profile in profiles if profile.available]
    configured_provider = str(settings.supervisor_model_provider or "").strip().lower()
    configured_model = str(settings.supervisor_model_name or "").strip()

    for profile in available_profiles:
        if profile.provider == configured_provider and profile.model == configured_model:
            return profile, "Supervisor Agent는 설정된 상위 모델을 고정 사용한다."

    provider_profiles = [profile for profile in available_profiles if profile.provider == configured_provider]
    if provider_profiles:
        chosen = sorted(provider_profiles, key=lambda item: item.quality_score, reverse=True)[0]
        return chosen, "Supervisor 설정 모델명이 후보와 달라 같은 provider의 최고 품질 모델로 대체했다."

    if available_profiles:
        chosen = sorted(available_profiles, key=lambda item: item.quality_score, reverse=True)[0]
        return chosen, "Supervisor 설정 provider를 사용할 수 없어 사용 가능한 최고 품질 모델로 대체했다."

    # 이 경로는 보통 오지 않는다. vLLM 후보가 항상 만들어지기 때문이다.
    fallback = profiles[0]
    return fallback, "사용 가능한 모델 후보가 없어 vLLM fallback을 사용한다."


def find_profile_for_assignment(profiles: list[ModelProfile], assignment: dict[str, Any] | None) -> ModelProfile | None:
    """이전 model_assignment에 해당하는 후보 profile을 찾는다."""

    if not assignment:
        return None
    provider = str(assignment.get("provider") or "").lower()
    model = str(assignment.get("model") or "")
    for profile in profiles:
        if profile.provider == provider and profile.model == model:
            return profile
    return None


def select_escalation_model(
    *,
    agent_id: str,
    stage_name: str,
    call_kind: str,
    state: dict[str, Any] | None = None,
    previous_assignment: dict[str, Any] | None = None,
    failure_reason: str = "",
) -> dict[str, Any]:
    """timeout 이후 재시도에 사용할 상향 모델을 고른다.

    일반 Expert Agent는 이전보다 품질 점수가 높은 후보를 우선 선택한다.
    Supervisor는 이미 상위 모델일 수 있으므로, 같은 모델 반복 대신 가능한
    다른 고품질 provider를 먼저 보고, 없으면 같은 상위 모델을 더 긴 timeout으로
    재시도하도록 같은 assignment를 반환한다.
    """

    settings = get_settings()
    state = state or {}
    profiles = build_model_profiles()
    metrics = estimate_workload(
        agent_id=agent_id,
        stage_name=stage_name,
        call_kind=call_kind,
        state=state,
        target_seconds=settings.model_router_target_seconds,
    )
    available_profiles = [profile for profile in profiles if profile.available] or [profiles[0]]
    previous_profile = find_profile_for_assignment(available_profiles, previous_assignment)
    previous_quality = previous_profile.quality_score if previous_profile else 0.0
    previous_provider = previous_profile.provider if previous_profile else ""
    previous_model = previous_profile.model if previous_profile else ""

    total_tokens = metrics.estimated_input_tokens + metrics.estimated_output_tokens
    fitting_profiles = [
        profile
        for profile in available_profiles
        if total_tokens <= profile.context_window_tokens
    ] or available_profiles

    upgraded_profiles = [
        profile
        for profile in fitting_profiles
        if profile.quality_score > previous_quality + 0.01
        and not (profile.provider == previous_provider and profile.model == previous_model)
    ]

    if agent_id == SUPERVISOR_AGENT_ID and not upgraded_profiles:
        # Supervisor가 이미 최고 모델이면 같은 등급의 다른 provider를 우선 시도한다.
        upgraded_profiles = [
            profile
            for profile in fitting_profiles
            if profile.tier == "high"
            and not (profile.provider == previous_provider and profile.model == previous_model)
        ]

    if not upgraded_profiles:
        upgraded_profiles = [
            profile
            for profile in fitting_profiles
            if not (profile.provider == previous_provider and profile.model == previous_model)
        ]

    if upgraded_profiles:
        chosen_profile = sorted(
            upgraded_profiles,
            key=lambda item: (item.quality_score, item.speed_score, item.context_window_tokens),
            reverse=True,
        )[0]
        selected_by = "timeout_escalated_model"
        reason = (
            "이전 LLM 호출이 timeout되어 더 높은 품질 또는 다른 고품질 provider 모델로 재시도한다. "
            f"실패 원인: {failure_reason}"
        )
    else:
        chosen_profile = previous_profile or sorted(fitting_profiles, key=lambda item: item.quality_score, reverse=True)[0]
        selected_by = "timeout_retry_same_upper_model"
        reason = (
            "사용 가능한 더 높은 모델이 없어 같은 상위 모델을 더 긴 timeout으로 재시도한다. "
            f"실패 원인: {failure_reason}"
        )

    return build_assignment(
        agent_id=agent_id,
        stage_name=stage_name,
        call_kind=call_kind,
        profile=chosen_profile,
        metrics=metrics,
        selected_by=selected_by,
        reason=reason,
        score_cards=[
            {
                "provider": profile.provider,
                "model": profile.model,
                "tier": profile.tier,
                "quality_score": profile.quality_score,
                "speed_score": profile.speed_score,
                "estimated_cost_usd": estimate_model_cost(profile, metrics),
                "cost_calculation": estimate_model_cost_breakdown(profile, metrics),
            }
            for profile in sorted(
                fitting_profiles,
                key=lambda item: (item.quality_score, item.speed_score),
                reverse=True,
            )[:6]
        ],
    )


def select_agent_model(
    *,
    agent_id: str,
    stage_name: str,
    call_kind: str,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Supervisor 정책에 따라 Agent별 LLM 모델을 선택한다.

    선택 흐름:
    1. state를 기반으로 workload metrics를 만든다.
    2. router가 꺼져 있으면 vLLM 기본 모델을 쓴다.
    3. Supervisor Agent면 상위 모델 고정 정책을 쓴다.
    4. Expert Agent면 score_model 수식으로 후보를 비교한다.
    5. 선택 결과와 상위 후보 score cards를 trace에 남긴다.
    """

    settings = get_settings()
    state = state or {}
    profiles = build_model_profiles()
    metrics = estimate_workload(
        agent_id=agent_id,
        stage_name=stage_name,
        call_kind=call_kind,
        state=state,
        target_seconds=settings.model_router_target_seconds,
    )

    if not settings.model_router_enabled:
        vllm_profile = next((profile for profile in profiles if profile.provider == "vllm"), profiles[0])
        return build_assignment(
            agent_id=agent_id,
            stage_name=stage_name,
            call_kind=call_kind,
            profile=vllm_profile,
            metrics=metrics,
            selected_by="router_disabled_vllm_default",
            reason="MODEL_ROUTER_ENABLED=false 이므로 .env의 vLLM 모델을 사용한다.",
            score_cards=[],
        )

    if agent_id == SUPERVISOR_AGENT_ID:
        profile, reason = choose_supervisor_profile(profiles)
        return build_assignment(
            agent_id=agent_id,
            stage_name=stage_name,
            call_kind=call_kind,
            profile=profile,
            metrics=metrics,
            selected_by="supervisor_fixed_upper_model",
            reason=reason,
            score_cards=[],
        )

    available_profiles = [profile for profile in profiles if profile.available]
    if not available_profiles:
        available_profiles = [profiles[0]]

    total_tokens = metrics.estimated_input_tokens + metrics.estimated_output_tokens
    quality_floor = max(0.0, metrics.required_quality_score - settings.model_router_quality_floor_margin)
    context_fitting_profiles = [
        profile
        for profile in available_profiles
        if total_tokens <= profile.context_window_tokens
    ]
    # 품질 하한은 "무조건 가장 비싼 모델을 쓰자"가 아니라 "현재 업무 난이도보다
    # 너무 약한 모델은 제외하자"에 가깝다. 하한을 통과한 후보 안에서는 비용
    # 민감도와 속도 점수 때문에 하위 GPT/vLLM이 충분히 선택될 수 있다.
    eligible_profiles = [
        profile
        for profile in context_fitting_profiles
        if profile.quality_score >= quality_floor
    ]
    selection_profiles = eligible_profiles or context_fitting_profiles or available_profiles

    candidate_costs = [estimate_model_cost(profile, metrics) for profile in available_profiles]
    max_candidate_cost = max(candidate_costs) if candidate_costs else 0.0
    score_cards = [
        score_model(
            profile=profile,
            metrics=metrics,
            max_candidate_cost=max_candidate_cost,
            cost_sensitivity=settings.model_router_cost_sensitivity,
        )
        for profile in available_profiles
    ]
    for card in score_cards:
        profile = next(
            item
            for item in available_profiles
            if item.provider == card["provider"] and item.model == card["model"]
        )
        card["quality_floor"] = round(quality_floor, 4)
        card["eligible_for_selection"] = profile in selection_profiles

    selection_cards = [card for card in score_cards if card["eligible_for_selection"]] or score_cards
    selection_cards.sort(
        key=lambda item: (
            item["score"],
            -item["estimated_cost_usd"],
            item["profile"]["quality_score"],
        ),
        reverse=True,
    )
    score_cards.sort(
        key=lambda item: (
            item["eligible_for_selection"],
            item["score"],
            -item["estimated_cost_usd"],
            item["profile"]["quality_score"],
        ),
        reverse=True,
    )
    # 같은 점수라면 비용이 낮은 모델을 우선하도록 `-estimated_cost_usd`를
    # 정렬 key에 넣었다. 그래도 품질 점수는 마지막 tie-breaker로 남긴다.
    chosen_card = selection_cards[0]
    chosen_profile = next(
        profile
        for profile in available_profiles
        if profile.provider == chosen_card["provider"] and profile.model == chosen_card["model"]
    )

    reason = (
        "Supervisor 모델 라우터가 자료량, 처리 대상 수, 예상 시간, 모델 품질, "
        "context 적합도, 추정 비용을 비교했다. Supervisor가 아닌 호출은 요구 품질 하한을 넘는 "
        "후보 중 가격 대비 효율 점수가 가장 높은 모델을 선택한다."
    )
    return build_assignment(
        agent_id=agent_id,
        stage_name=stage_name,
        call_kind=call_kind,
        profile=chosen_profile,
        metrics=metrics,
        selected_by="supervisor_cost_performance_formula",
        reason=reason,
        score_cards=score_cards[:6],
    )


def build_assignment(
    *,
    agent_id: str,
    stage_name: str,
    call_kind: str,
    profile: ModelProfile,
    metrics: WorkloadMetrics,
    selected_by: str,
    reason: str,
    score_cards: list[dict[str, Any]],
) -> dict[str, Any]:
    """모델 선택 결과를 workflow_state에 저장할 표준 payload로 만든다."""

    return {
        "agent_id": agent_id,
        "stage_name": stage_name,
        "call_kind": call_kind,
        "provider": profile.provider,
        "model": profile.model,
        "tier": profile.tier,
        "selected_by": selected_by,
        "reason": reason,
        "workload_metrics": metrics.to_dict(),
        "selected_profile": profile.to_public_dict(),
        "estimated_cost_usd": estimate_model_cost(profile, metrics),
        "cost_calculation": estimate_model_cost_breakdown(profile, metrics),
        "score_cards": score_cards,
    }


def compact_model_assignment(assignment: dict[str, Any] | None) -> dict[str, Any]:
    """LLM call record에 넣기 좋은 짧은 모델 선택 요약."""

    if not assignment:
        return {}
    return {
        "provider": assignment.get("provider"),
        "model": assignment.get("model"),
        "tier": assignment.get("tier"),
        "selected_by": assignment.get("selected_by"),
        "estimated_cost_usd": assignment.get("estimated_cost_usd"),
        "cost_calculation": assignment.get("cost_calculation", {}),
        "reason": assignment.get("reason"),
        "workload_metrics": assignment.get("workload_metrics", {}),
    }
