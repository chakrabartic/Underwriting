import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class AppetiteEligibilityAgent:
    """
    Subagent B: Appetite & Eligibility
    Role: Evaluates the extracted entities against the carrier's codified appetite guide.
    Constraints: Outputs decisions bound strictly to documented appetite rule IDs.
    """
    def __init__(self):
        # In a real scenario, this might pull rules from a database or a rules engine API.
        pass

    def evaluate(self, quote_id: str, extracted_data: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"Evaluating appetite for quote: {quote_id}")
        
        decision = "ELIGIBLE"
        reasons = []
        rule_traces = []

        # Example rule evaluation based on Intake Extraction
        if "business_name" in extracted_data:
            # Fake logic for demonstration
            business_name = extracted_data["business_name"]["value"].lower()
            if "logistics" in business_name:
                rule_traces.append("APP_RULE_001_LOGISTICS")
                reasons.append("Logistics operations require special referral.")
                decision = "REFERRAL"

        if "revenue" in extracted_data:
            rev_str = extracted_data["revenue"]["value"].replace("$", "").replace(",", "")
            try:
                revenue = float(rev_str)
                if revenue > 5000000:
                    rule_traces.append("APP_RULE_002_HIGH_REVENUE")
                    reasons.append("Revenue exceeds $5M threshold.")
                    if decision == "ELIGIBLE":
                        decision = "REFERRAL"
            except ValueError:
                pass

        return {
            "status": "COMPLETED",
            "decision": decision,
            "reasons": reasons,
            "rule_traces": rule_traces
        }

