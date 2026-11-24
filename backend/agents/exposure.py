"""Subagent D: Exposure & Risk Summary Agent.

Synthesizes structured intake, appetite, enrichment, and deterministic rating
traces into an explainable underwriting briefing using the modern Gemini
Interactions API (`gemini-4-hydrogen`), mechanically gated by `GroundingGateway`
to guarantee 0% uncited or numerically unattested claims (Specification 03).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.adapters import (
    DeterministicGroundedSynthesizer,
    GeminiInteractionsModelAdapter,
)
from backend.config import ExecutionMode
from backend.grounding import CitationRegistry, GroundingGateway
from backend.models import StructuredExposureBriefingSchema
from backend.ports import LanguageModelPort
from backend.security import AgentGatewayProxy

logger = logging.getLogger(__name__)

AGENT_NAME = "ExposureRiskSummaryAgent"


class ExposureRiskSummaryAgent:
    """Produces mechanically grounded natural-language risk summaries."""

    def __init__(
        self,
        project_id: str = "chayan-genai-bb",
        location: str = "us-central1",
        *,
        model: str = "gemini-4-hydrogen",
        execution_mode: ExecutionMode = ExecutionMode.LOCAL_SANDBOX,
        llm_adapter: LanguageModelPort | None = None,
        grounding_gateway: GroundingGateway | None = None,
        gateway: AgentGatewayProxy | None = None,
    ) -> None:
        self.project_id = project_id
        self.location = location
        self._gateway = gateway
        self._grounding_gateway = grounding_gateway or GroundingGateway(
            strict_mode=False
        )

        if llm_adapter is not None:
            self._llm = llm_adapter
        elif execution_mode == ExecutionMode.GCP_PRODUCTION:
            self._llm = GeminiInteractionsModelAdapter(
                project_id=project_id, location=location, model=model
            )
        else:
            self._llm = DeterministicGroundedSynthesizer()

    def synthesize(
        self,
        quote_id: str,
        extracted_data: dict[str, Any],
        enrichment_data: dict[str, Any],
        *,
        appetite_data: dict[str, Any] | None = None,
        rating_data: dict[str, Any] | None = None,
        citation_registry: CitationRegistry | None = None,
    ) -> dict[str, Any]:
        """Generates a risk summary and validates every claim through GroundingGateway."""
        logger.info(
            "Synthesizing grounded risk summary for quote_id=%s model=%s",
            quote_id,
            self._llm.model_name,
        )

        registry = citation_registry or CitationRegistry.from_workflow_artifacts(
            quote_id,
            intake_extracted_data=extracted_data,
            appetite_result=appetite_data,
            enrichment_data=enrichment_data,
            rating_result=rating_data,
        )

        rating_context: dict[str, Any] = {}
        if rating_data:
            version = rating_data.get("engine_version", "v1.4.2")
            rating_context = {
                "engine_version": version,
                "adjusted_premium": rating_data.get("adjusted_premium"),
                "risk_score": rating_data.get("risk_score"),
                "decision": rating_data.get("decision"),
                "rule_citation_uris": [
                    f"rule://rating/{version}/{r}"
                    for r in rating_data.get("execution_trace", [])
                ],
            }

        context_payload = {
            "intake_data": extracted_data,
            "enrichment_data": enrichment_data,
            "appetite_data": appetite_data or {},
            "rating_data": rating_context,
            "available_citations": {
                uri: rec.to_dict() for uri, rec in registry.all_records().items()
            },
        }

        system_instruction = (
            "You are a senior commercial insurance underwriting analyst. "
            "Produce a concise risk briefing as a JSON list of assertions. "
            "Every assertion MUST cite one or more exact `citation_uris` from "
            "`available_citations` and MUST NOT state any number, rate, or fact "
            "not explicitly present in those cited sources."
        )
        prompt = f"CONTEXT_JSON:\n{json.dumps(context_payload, sort_keys=True)}"
        schema = StructuredExposureBriefingSchema.model_json_schema()

        def _invoke_model() -> str:
            return self._llm.generate_structured_json(
                system_instruction=system_instruction,
                prompt=prompt,
                json_schema=schema,
            )

        if self._gateway is None:
            raw_json = _invoke_model()
        else:
            raw_json = self._gateway.authorize_and_execute(
                agent_name=AGENT_NAME,
                quote_id=quote_id,
                tool_name="GeminiInteractions.SynthesizeRiskSummary",
                required_scope="genai:synthesize_summary",
                operation=_invoke_model,
            )

        parsed_payload = json.loads(raw_json)
        raw_assertions = parsed_payload.get("assertions", [])
        validation_report = self._grounding_gateway.validate_assertions(
            raw_assertions, registry
        )

        return {
            "status": "COMPLETED",
            "summary": validation_report.render_summary_text(),
            "assertions": [
                a.model_dump(mode="json")
                for a in validation_report.verified_assertions
            ],
            "grounding_context_used": True,
            "grounding_verified": validation_report.is_fully_grounded,
            "grounding_report": validation_report.to_dict(),
            "model_used": self._llm.model_name,
        }
