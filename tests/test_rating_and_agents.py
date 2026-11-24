"""Unit, determinism, and seeded fuzz/property tests for rating and domain subagents."""

from __future__ import annotations

from decimal import Decimal
import random

import pytest

from backend.agents.appetite import AppetiteEligibilityAgent
from backend.agents.quote_gen import QuoteGenerationAgent
from backend.agents.rating_engine import SymbolicRatingEngine


def test_symbolic_rating_determinism_and_digest_stability() -> None:
    """Identical inputs + rule version MUST yield bit-identical outputs and hashes."""
    engine = SymbolicRatingEngine(version="v1.4.2")
    extracted = {"business_name": {"value": "Acme Corp Logistics"}}
    enrichment = {
        "property_characteristics": {
            "roof_age_years": {
                "value": 22,
                "grounding_trace": {"citation_uri": "apigee://Q1/v1/property#roof_age_years"},
            },
            "construction_type": {
                "value": "Masonry Non-Combustible",
                "grounding_trace": {"citation_uri": "apigee://Q1/v1/property#construction_type"},
            },
        },
        "loss_history": {
            "claims_last_5_years": {
                "value": 1,
                "grounding_trace": {"citation_uri": "apigee://Q1/v1/claims#claims_last_5_years"},
            },
            "total_incurred": {
                "value": 15000,
                "grounding_trace": {"citation_uri": "apigee://Q1/v1/claims#total_incurred"},
            },
        },
    }

    first = engine.calculate_premium("Q1", extracted, enrichment, appetite_decision="REFERRAL")
    second = engine.calculate_premium("Q2", extracted, enrichment, appetite_decision="REFERRAL")

    assert first["adjusted_premium"] == 7500.0
    assert first["risk_score"] == 71.0
    assert first["decision"] == "REFERRAL"
    assert first["input_digest"] == second["input_digest"]
    assert first["output_digest"] == second["output_digest"]
    assert first["execution_trace"] == second["execution_trace"]


def test_quote_generation_exact_decimal_cent_math() -> None:
    """Verifies exact cent rounding without IEEE-754 float drift (e.g. 7500 * 1.15 == 8625.0)."""
    quote_agent = QuoteGenerationAgent(quotes_bucket="prod-quotes")
    res = quote_agent.generate_quote_options(
        "QTE-7500",
        {
            "adjusted_premium": 7500.0,
            "decision": "REFERRAL",
            "output_digest": "abc123digest",
        },
    )
    by_tier = {opt["tier"]: opt["premium"] for opt in res["quote_options"]}
    assert by_tier == {
        "Standard": 7500.0,
        "Premium": 8625.0,
        "Economy": 6375.0,
    }


def test_quote_generation_blocks_declined_submissions() -> None:
    """Declined submissions must never emit bindable quote tiers."""
    quote_agent = QuoteGenerationAgent()
    res = quote_agent.generate_quote_options(
        "QTE-DEC",
        {"adjusted_premium": 12000.0, "decision": "DECLINE", "output_digest": "sha"},
    )
    assert res["status"] == "DECLINED_NO_QUOTE"
    assert res["quote_options"] == []
    assert res["document_url"].endswith("_decline_notice.pdf")


def test_symbolic_rating_property_fuzz_invariants() -> None:
    """Property/fuzz test across 200 randomized inputs verifying mathematical invariants."""
    rng = random.Random(42)
    engine = SymbolicRatingEngine(version="v1.4.2")
    constructions = ["Fire Resistive", "Masonry Non-Combustible", "Frame"]

    for idx in range(200):
        roof_age = rng.randint(0, 60)
        claims = rng.randint(0, 8)
        incurred = rng.randint(0, 500_000)
        const_type = rng.choice(constructions)

        enrichment_base = {
            "property_characteristics": {
                "roof_age_years": {"value": roof_age, "grounding_trace": {}},
                "construction_type": {"value": const_type, "grounding_trace": {}},
            },
            "loss_history": {
                "claims_last_5_years": {"value": claims, "grounding_trace": {}},
                "total_incurred": {"value": incurred, "grounding_trace": {}},
            },
        }
        res_base = engine.calculate_premium_typed(f"FUZZ-{idx}", {}, enrichment_base)

        # Invariant 1: Score bounded within [0.0, 100.0] and premium >= $500 floor
        assert Decimal("0.0") <= res_base.risk_score <= Decimal("100.0")
        assert res_base.adjusted_premium >= Decimal("500.00")
        assert res_base.adjusted_premium.as_tuple().exponent == -2

        # Invariant 2: Monotonicity with respect to additional claims
        enrichment_more_claims = {
            **enrichment_base,
            "loss_history": {
                "claims_last_5_years": {"value": claims + 1, "grounding_trace": {}},
                "total_incurred": {"value": incurred, "grounding_trace": {}},
            },
        }
        res_higher = engine.calculate_premium_typed(f"FUZZ-HI-{idx}", {}, enrichment_more_claims)
        assert res_higher.adjusted_premium > res_base.adjusted_premium
        assert res_higher.risk_score >= res_base.risk_score


def test_symbolic_rating_rejects_negative_inputs() -> None:
    """Negative roof age or negative claim counts must raise ValueError immediately."""
    engine = SymbolicRatingEngine()
    bad_enrichment = {
        "property_characteristics": {"roof_age_years": {"value": -3}},
        "loss_history": {"claims_last_5_years": {"value": 0}, "total_incurred": {"value": 0}},
    }
    with pytest.raises(ValueError, match="non-negative"):
        engine.calculate_premium("QTE-NEG", {}, bad_enrichment)


def test_appetite_agent_eligibility_referral_decline_and_malformed_revenue() -> None:
    """Verifies all codified carrier appetite branches including malformed currency handling."""
    agent = AppetiteEligibilityAgent()

    eligible = agent.evaluate(
        "Q-ELIG",
        {
            "business_name": {"value": "Harborview Books LLC"},
            "revenue": {"value": "$1,250,000"},
        },
    )
    assert eligible["decision"] == "ELIGIBLE"
    assert eligible["rule_traces"] == ["APP_RULE_000_STANDARD_ELIGIBLE"]

    ineligible = agent.evaluate(
        "Q-INELIG",
        {
            "business_name": {"value": "Apex Pyrotechnics Corp"},
            "revenue": {"value": "$30,000,000"},
        },
    )
    assert ineligible["decision"] == "INELIGIBLE"
    assert "APP_RULE_003_PROHIBITED_HAZARD_CLASS" in ineligible["rule_traces"]
    assert "APP_RULE_004_EXCESS_REVENUE_CAP" in ineligible["rule_traces"]

    malformed = agent.evaluate(
        "Q-MAL",
        {
            "business_name": {"value": "Standard Office Co"},
            "revenue": {"value": "TBD_UPON_AUDIT"},
        },
    )
    assert malformed["decision"] == "REFERRAL"
    assert "APP_RULE_005_UNVERIFIED_REVENUE_DATA" in malformed["rule_traces"]
