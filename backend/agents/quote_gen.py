"""Subagent F: Quote & Document Generation Agent.

Compiles deterministic deductible/coverage quote tiers strictly from the
`SymbolicRatingEngine` output using exact `Decimal` cent quantization.
Refuses to emit bindable quote tiers when the rating decision is `DECLINE`.
"""

from __future__ import annotations

from decimal import Decimal
import logging
from typing import Any

from backend.models import QuoteOption, RatingDecision, quantize_money
from backend.security import AgentGatewayProxy

logger = logging.getLogger(__name__)

AGENT_NAME = "QuoteGenerationAgent"

QUOTE_TIER_SCHEDULE: tuple[tuple[str, int, Decimal, str], ...] = (
    ("Standard", 1000, Decimal("1.00"), "QUOTE_TIER_RULE_STD_100"),
    ("Premium", 500, Decimal("1.15"), "QUOTE_TIER_RULE_PRM_115"),
    ("Economy", 2500, Decimal("0.85"), "QUOTE_TIER_RULE_ECO_085"),
)


class QuoteGenerationAgent:
    """Formats deterministic multi-tier quote proposals without altering base math."""

    def __init__(
        self,
        quotes_bucket: str = "underwriting-quotes",
        *,
        gateway: AgentGatewayProxy | None = None,
    ) -> None:
        self.quotes_bucket = quotes_bucket
        self._gateway = gateway

    def generate_quote_options(
        self, quote_id: str, rating_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Generates priced quote tiers or records a non-quoted decline notice."""
        logger.info("Generating quote options for quote_id=%s", quote_id)

        def _generate() -> dict[str, Any]:
            decision = str(rating_data.get("decision", RatingDecision.STP.value))
            if decision == RatingDecision.DECLINE.value:
                return {
                    "status": "DECLINED_NO_QUOTE",
                    "quote_options": [],
                    "document_url": (
                        f"gs://{self.quotes_bucket}/outbound/{quote_id}_decline_notice.pdf"
                    ),
                    "rating_output_digest": rating_data.get("output_digest", ""),
                }

            adjusted_premium = quantize_money(rating_data["adjusted_premium"])
            typed_options = [
                QuoteOption(
                    tier=tier_name,
                    deductible=deductible,
                    premium=quantize_money(adjusted_premium * multiplier),
                    multiplier=multiplier,
                    rule_id=rule_id,
                )
                for tier_name, deductible, multiplier, rule_id in QUOTE_TIER_SCHEDULE
            ]

            return {
                "status": "COMPLETED",
                "quote_options": [
                    {
                        "tier": opt.tier,
                        "deductible": opt.deductible,
                        "premium": float(opt.premium),
                        "multiplier": float(opt.multiplier),
                        "rule_id": opt.rule_id,
                    }
                    for opt in typed_options
                ],
                "document_url": (
                    f"gs://{self.quotes_bucket}/outbound/{quote_id}_proposal.pdf"
                ),
                "rating_output_digest": rating_data.get("output_digest", ""),
            }

        if self._gateway is None:
            return _generate()
        return self._gateway.authorize_and_execute(
            agent_name=AGENT_NAME,
            quote_id=quote_id,
            tool_name="CloudStorage.WriteQuoteProposal",
            required_scope="gcs:write_quote_proposal",
            operation=_generate,
        )
