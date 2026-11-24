"""Subagent E: Symbolic Rating & Scoring Engine (Non-LLM Deterministic Layer).

ARCHITECTURAL MANDATE (Specification 02):
- ZERO LLM CALLS and ZERO external network imports.
- Exact `decimal.Decimal` arithmetic quantized to `$0.01` (`ROUND_HALF_UP`).
- Cryptographic SHA-256 input/output digests proving deterministic replayability.
- Every rate modifier attaches a versioned `Rule_ID` and source citation URI.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import logging
from typing import Any

from backend.models import (
    AppetiteDecision,
    RatingDecision,
    RatingFactor,
    RatingResult,
    canonical_sha256,
    quantize_money,
)
from backend.security import AgentGatewayProxy

logger = logging.getLogger(__name__)

AGENT_NAME = "SymbolicRatingEngine"

SCORE_PRECISION = Decimal("0.1")


def _to_non_negative_int(raw: Any, field_name: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Rating input {field_name!r} must be an integer, got {raw!r}") from exc
    if value < 0:
        raise ValueError(f"Rating input {field_name!r} must be non-negative, got {value}")
    return value


def _to_non_negative_decimal(raw: Any, field_name: str) -> Decimal:
    try:
        value = Decimal(str(raw).replace("$", "").replace(",", "").strip())
    except Exception as exc:
        raise ValueError(f"Rating input {field_name!r} must be numeric, got {raw!r}") from exc
    if value < 0:
        raise ValueError(f"Rating input {field_name!r} must be non-negative, got {value}")
    return value


class SymbolicRatingEngine:
    """Purely symbolic, version-controlled insurance pricing and risk-scoring engine."""

    def __init__(
        self,
        version: str = "v1.4.2",
        base_rate: Decimal | str | float = Decimal("5000.00"),
        *,
        gateway: AgentGatewayProxy | None = None,
    ) -> None:
        self.version = version
        self.base_rate: Decimal = quantize_money(base_rate)
        self._gateway = gateway

    def calculate_premium_typed(
        self,
        quote_id: str,
        extracted_data: dict[str, Any],
        enrichment_data: dict[str, Any],
        *,
        appetite_decision: str | None = None,
    ) -> RatingResult:
        """Executes deterministic pricing and returns an immutable `RatingResult`."""
        logger.info(
            "SymbolicRatingEngine evaluating quote_id=%s engine_version=%s",
            quote_id,
            self.version,
        )

        def _compute() -> RatingResult:
            canonical_input = {
                "engine_version": self.version,
                "base_rate": self.base_rate,
                "extracted_data": extracted_data,
                "enrichment_data": enrichment_data,
                "appetite_decision": appetite_decision,
            }
            input_digest = canonical_sha256(canonical_input)

            premium = self.base_rate
            execution_trace: list[str] = ["RATE_RULE_000_BASE_RATE"]
            factors: list[RatingFactor] = []

            props = enrichment_data.get("property_characteristics", {})
            losses = enrichment_data.get("loss_history", {})

            # Rule 1: Construction type credits / surcharges
            construction_entry = props.get("construction_type", {})
            construction_val = str(construction_entry.get("value", "")).strip().lower()
            construction_trace = dict(construction_entry.get("grounding_trace", {}))
            if construction_val == "fire resistive":
                credit = Decimal("-500.00")
                premium += credit
                rule_id = "RATE_RULE_008_FIRE_RESISTIVE_CREDIT"
                execution_trace.append(rule_id)
                factors.append(
                    RatingFactor(
                        description="Fire Resistive Construction Credit",
                        impact=quantize_money(credit),
                        rule_id=rule_id,
                        citation_uri=f"rule://rating/{self.version}/{rule_id}",
                        input_citation_uri=construction_trace.get("citation_uri"),
                        grounding_reference=construction_trace,
                    )
                )
            elif construction_val == "frame":
                surcharge = Decimal("1250.00")
                premium += surcharge
                rule_id = "RATE_RULE_009_FRAME_CONSTRUCTION_SURCHARGE"
                execution_trace.append(rule_id)
                factors.append(
                    RatingFactor(
                        description="Combustible Frame Construction Surcharge",
                        impact=quantize_money(surcharge),
                        rule_id=rule_id,
                        citation_uri=f"rule://rating/{self.version}/{rule_id}",
                        input_citation_uri=construction_trace.get("citation_uri"),
                        grounding_reference=construction_trace,
                    )
                )

            # Rule 2: Roof age surcharge (> 20 years)
            roof_entry = props.get("roof_age_years", {})
            roof_age = _to_non_negative_int(
                roof_entry.get("value", 0), "roof_age_years"
            )
            roof_trace = dict(roof_entry.get("grounding_trace", {}))
            if roof_age > 20:
                surcharge = Decimal("1500.00")
                premium += surcharge
                rule_id = "RATE_RULE_012_ROOF_AGE_SURCHARGE"
                execution_trace.append(rule_id)
                factors.append(
                    RatingFactor(
                        description="Roof Age > 20 Years",
                        impact=quantize_money(surcharge),
                        rule_id=rule_id,
                        citation_uri=f"rule://rating/{self.version}/{rule_id}",
                        input_citation_uri=roof_trace.get("citation_uri"),
                        grounding_reference=roof_trace,
                    )
                )

            # Rule 3: 5-year claims frequency surcharge
            claims_entry = losses.get("claims_last_5_years", {})
            claims = _to_non_negative_int(
                claims_entry.get("value", 0), "claims_last_5_years"
            )
            claims_trace = dict(claims_entry.get("grounding_trace", {}))
            if claims > 0:
                surcharge = quantize_money(Decimal("1000.00") * Decimal(claims))
                premium += surcharge
                rule_id = "RATE_RULE_025_CLAIMS_HISTORY_SURCHARGE"
                execution_trace.append(rule_id)
                factors.append(
                    RatingFactor(
                        description=f"{claims} Claims in past 5 years",
                        impact=surcharge,
                        rule_id=rule_id,
                        citation_uri=f"rule://rating/{self.version}/{rule_id}",
                        input_citation_uri=claims_trace.get("citation_uri"),
                        grounding_reference=claims_trace,
                    )
                )

            # Rule 4: Severe incurred loss surcharge (> $100,000)
            incurred_entry = losses.get("total_incurred", {})
            total_incurred = _to_non_negative_decimal(
                incurred_entry.get("value", 0), "total_incurred"
            )
            incurred_trace = dict(incurred_entry.get("grounding_trace", {}))
            if total_incurred > Decimal("100000"):
                surcharge = Decimal("2500.00")
                premium += surcharge
                rule_id = "RATE_RULE_031_SEVERE_LOSS_LOAD"
                execution_trace.append(rule_id)
                factors.append(
                    RatingFactor(
                        description="5-Year Total Incurred > $100,000",
                        impact=quantize_money(surcharge),
                        rule_id=rule_id,
                        citation_uri=f"rule://rating/{self.version}/{rule_id}",
                        input_citation_uri=incurred_trace.get("citation_uri"),
                        grounding_reference=incurred_trace,
                    )
                )

            adjusted_premium = quantize_money(max(Decimal("500.00"), premium))

            # Deterministic risk score calculation (0.0 - 100.0)
            construction_score_adj = Decimal("0")
            if construction_val == "fire resistive":
                construction_score_adj = Decimal("-5")
            elif construction_val == "frame":
                construction_score_adj = Decimal("10")

            raw_score = (
                Decimal("50")
                + (Decimal(roof_age) * Decimal("0.5"))
                + (Decimal(claims) * Decimal("10"))
                + construction_score_adj
            )
            clamped_score = min(
                Decimal("100.0"), max(Decimal("0.0"), raw_score)
            ).quantize(SCORE_PRECISION, rounding=ROUND_HALF_UP)

            # Reconcile routing decision with upstream appetite & score thresholds
            if (
                appetite_decision == AppetiteDecision.INELIGIBLE.value
                or clamped_score >= Decimal("85.0")
            ):
                decision = RatingDecision.DECLINE
                execution_trace.append("RATE_RULE_099_DECLINE_THRESHOLD")
            elif (
                appetite_decision == AppetiteDecision.REFERRAL.value
                or clamped_score >= Decimal("60.0")
            ):
                decision = RatingDecision.REFERRAL
            else:
                decision = RatingDecision.STP

            output_digest = canonical_sha256({
                "input_digest": input_digest,
                "base_premium": self.base_rate,
                "adjusted_premium": adjusted_premium,
                "risk_score": clamped_score,
                "decision": decision.value,
                "engine_version": self.version,
                "execution_trace": execution_trace,
                "factors": [f.model_dump(mode="json") for f in factors],
            })

            return RatingResult(
                base_premium=self.base_rate,
                adjusted_premium=adjusted_premium,
                risk_score=clamped_score,
                decision=decision,
                engine_version=self.version,
                execution_trace=execution_trace,
                factors=factors,
                input_digest=input_digest,
                output_digest=output_digest,
            )

        if self._gateway is None:
            return _compute()
        return self._gateway.authorize_and_execute(
            agent_name=AGENT_NAME,
            quote_id=quote_id,
            tool_name="SymbolicRatingEngine.CalculatePremium",
            required_scope="rules:calculate_rating",
            operation=_compute,
        )

    def calculate_premium(
        self,
        quote_id: str,
        extracted_data: dict[str, Any],
        enrichment_data: dict[str, Any],
        *,
        appetite_decision: str | None = None,
    ) -> dict[str, Any]:
        """Calculates deterministic pricing and returns a JSON-serializable dict."""
        result = self.calculate_premium_typed(
            quote_id=quote_id,
            extracted_data=extracted_data,
            enrichment_data=enrichment_data,
            appetite_decision=appetite_decision,
        )
        return result.to_legacy_dict()
