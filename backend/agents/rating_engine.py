import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class SymbolicRatingEngine:
    """
    Subagent E: Symbolic Rating & Scoring Engine (Non-LLM)
    Role: Deterministic rules layer. Calculates premiums, applies risk modifiers.
    Constraints: ZERO LLM CALLS.
    """
    def __init__(self):
        self.version = "v1.4.2"
        self.base_rate = 5000.0

    def calculate_premium(self, quote_id: str, extracted_data: Dict[str, Any], enrichment_data: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Calculating deterministic premium for quote: {quote_id} using version {self.version}")
        
        premium = self.base_rate
        execution_trace = ["RATE_RULE_000_BASE_RATE"]
        factors = []

        # Example deterministic logic
        props = enrichment_data.get("property_characteristics", {})
        roof_age = props.get("roof_age_years", {}).get("value", 0)
        if roof_age > 20:
            surcharge = 1500.0
            premium += surcharge
            execution_trace.append("RATE_RULE_012_ROOF_AGE_SURCHARGE")
            factors.append({
                "description": "Roof Age > 20 Years",
                "impact": surcharge,
                "rule_id": "RATE_RULE_012_ROOF_AGE_SURCHARGE",
                "grounding_reference": props["roof_age_years"].get("grounding_trace")
            })

        claims = enrichment_data.get("loss_history", {}).get("claims_last_5_years", {}).get("value", 0)
        if claims > 0:
            surcharge = 1000.0 * claims
            premium += surcharge
            execution_trace.append("RATE_RULE_025_CLAIMS_HISTORY_SURCHARGE")
            factors.append({
                "description": f"{claims} Claims in past 5 years",
                "impact": surcharge,
                "rule_id": "RATE_RULE_025_CLAIMS_HISTORY_SURCHARGE",
                "grounding_reference": enrichment_data["loss_history"]["claims_last_5_years"].get("grounding_trace")
            })

        # Calculate Risk Score (0-100)
        risk_score = min(100, max(0, 50 + (roof_age * 0.5) + (claims * 10)))
        
        decision = "STP" if risk_score < 60 else "REFERRAL"

        return {
            "status": "COMPLETED",
            "base_premium": self.base_rate,
            "adjusted_premium": premium,
            "risk_score": risk_score,
            "decision": decision,
            "engine_version": self.version,
            "execution_trace": execution_trace,
            "factors": factors
        }

