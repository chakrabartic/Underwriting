"""Subagent B: Appetite & Eligibility Agent.

Evaluates extracted submission attributes against codified carrier appetite rules,
producing deterministic `ELIGIBLE`, `REFERRAL`, or `INELIGIBLE` decisions strictly
bound to versioned `APP_RULE_*` identifiers.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import logging
from typing import Any

from backend.models import AppetiteDecision
from backend.security import AgentGatewayProxy

logger = logging.getLogger(__name__)

AGENT_NAME = "AppetiteEligibilityAgent"

REFERRAL_REVENUE_THRESHOLD = Decimal("5000000")
INELIGIBLE_REVENUE_CEILING = Decimal("25000000")
PROHIBITED_HAZARD_KEYWORDS: tuple[str, ...] = (
    "pyrotechnic",
    "hazmat",
    "munitions",
    "explosive",
    "nuclear",
)
REFERRAL_CLASS_KEYWORDS: tuple[str, ...] = (
    "logistics",
    "warehousing",
    "trucking",
    "freight",
)


def parse_currency_decimal(raw_value: Any) -> Decimal:
    """Parses a formatted currency string (e.g., '$5,400,000') into a Decimal."""
    cleaned = str(raw_value).replace("$", "").replace(",", "").strip()
    if not cleaned:
        raise ValueError("Empty currency string.")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Unparseable currency amount: {raw_value!r}") from exc
    if value < 0:
        raise ValueError(f"Negative revenue is invalid: {raw_value!r}")
    return value


class AppetiteEligibilityAgent:
    """Deterministic carrier appetite evaluator with explicit rule lineage."""

    def __init__(self, *, gateway: AgentGatewayProxy | None = None) -> None:
        self._gateway = gateway

    def evaluate(
        self, quote_id: str, extracted_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Evaluates extracted intake entities against carrier appetite rules."""
        logger.info("Evaluating carrier appetite for quote_id=%s", quote_id)

        def _evaluate_rules() -> dict[str, Any]:
            decision = AppetiteDecision.ELIGIBLE
            reasons: list[str] = []
            rule_traces: list[str] = []

            biz_raw = str(extracted_data.get("business_name", {}).get("value", ""))
            occ_raw = str(extracted_data.get("occupancy_type", {}).get("value", ""))
            combined_text = f"{biz_raw} {occ_raw}".lower()

            if any(kw in combined_text for kw in PROHIBITED_HAZARD_KEYWORDS):
                decision = AppetiteDecision.INELIGIBLE
                rule_traces.append("APP_RULE_003_PROHIBITED_HAZARD_CLASS")
                reasons.append(
                    "Prohibited high-hazard operations fall outside carrier treaty appetite."
                )

            if any(kw in combined_text for kw in REFERRAL_CLASS_KEYWORDS):
                rule_traces.append("APP_RULE_001_LOGISTICS")
                reasons.append("Logistics operations require special referral.")
                if decision == AppetiteDecision.ELIGIBLE:
                    decision = AppetiteDecision.REFERRAL

            if "revenue" in extracted_data:
                raw_rev = extracted_data["revenue"].get("value")
                try:
                    revenue = parse_currency_decimal(raw_rev)
                    if revenue > INELIGIBLE_REVENUE_CEILING:
                        rule_traces.append("APP_RULE_004_EXCESS_REVENUE_CAP")
                        reasons.append(
                            f"Revenue exceeds ${INELIGIBLE_REVENUE_CEILING:,.0f} treaty cap."
                        )
                        decision = AppetiteDecision.INELIGIBLE
                    elif revenue > REFERRAL_REVENUE_THRESHOLD:
                        rule_traces.append("APP_RULE_002_HIGH_REVENUE")
                        reasons.append("Revenue exceeds $5M threshold.")
                        if decision == AppetiteDecision.ELIGIBLE:
                            decision = AppetiteDecision.REFERRAL
                except ValueError as exc:
                    logger.warning(
                        "Malformed revenue for quote_id=%s (%s); routing to referral.",
                        quote_id,
                        exc,
                    )
                    rule_traces.append("APP_RULE_005_UNVERIFIED_REVENUE_DATA")
                    reasons.append("Revenue format requires manual underwriter verification.")
                    if decision == AppetiteDecision.ELIGIBLE:
                        decision = AppetiteDecision.REFERRAL

            if not rule_traces:
                rule_traces.append("APP_RULE_000_STANDARD_ELIGIBLE")
                reasons.append("Submission meets all standard commercial appetite criteria.")

            return {
                "status": "COMPLETED",
                "decision": decision.value,
                "reasons": reasons,
                "rule_traces": rule_traces,
                "rule_citation_uris": [f"rule://appetite/{r}" for r in rule_traces],
            }

        if self._gateway is None:
            return _evaluate_rules()
        return self._gateway.authorize_and_execute(
            agent_name=AGENT_NAME,
            quote_id=quote_id,
            tool_name="AppetiteRuleEngine.Evaluate",
            required_scope="rules:evaluate_appetite",
            operation=_evaluate_rules,
        )
