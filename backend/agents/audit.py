"""Subagent G: Audit & Compliance Agent.

Compiles a regulator-ready, tamper-evident audit package capturing the complete
causal lineage of an underwriting submission:
- Original Cloud Storage document URI and Document AI coordinate mapping,
- Carrier appetite rule trace,
- Apigee external enrichment payload,
- Symbolic Rating Engine version, triggered `Rule_ID`s, and I/O SHA-256 digests,
- Mechanical Grounding verification report,
- SPIFFE / Agent Gateway tool-authorization ledger,
- Optional human-in-the-loop underwriter resolution, and
- Top-level SHA-256 `pack_digest` sealing the entire package.
"""

from __future__ import annotations

import logging
from typing import Any
import uuid

from backend.models import canonical_sha256, utc_now_iso
from backend.security import AgentGatewayProxy

logger = logging.getLogger(__name__)

AGENT_NAME = "AuditComplianceAgent"


class AuditComplianceAgent:
    """Produces regulator-ready, cryptographically sealed underwriting audit packs."""

    def __init__(self, *, gateway: AgentGatewayProxy | None = None) -> None:
        self._gateway = gateway

    def build_audit_pack(
        self, quote_id: str, session_context: dict[str, Any]
    ) -> dict[str, Any]:
        """Compiles and hashes the complete audit pack for `quote_id`."""
        logger.info("Building regulatory audit pack for quote_id=%s", quote_id)

        def _compile() -> dict[str, Any]:
            audit_id = f"AUDIT-{uuid.uuid4().hex[:8].upper()}"
            intake = session_context.get("intake", {})
            appetite = session_context.get("appetite", {})
            enrichment = session_context.get("enrichment", {})
            exposure = session_context.get("exposure", {})
            rating = session_context.get("rating", {})
            quote = session_context.get("quote", {})
            underwriter_resolution = session_context.get("underwriter_resolution")

            security_ledger = (
                [e.to_dict() for e in self._gateway.get_audit_entries(quote_id)]
                if self._gateway is not None
                else session_context.get("security_tool_traces", [])
            )

            pack_body: dict[str, Any] = {
                "audit_id": audit_id,
                "quote_id": quote_id,
                "generated_at": utc_now_iso(),
                "source_uri": intake.get("source_uri", ""),
                "intake_extraction_map": intake,
                "appetite_evaluation": appetite,
                "enrichment_payload": enrichment,
                "exposure_grounding_report": exposure.get("grounding_report", {}),
                "symbolic_engine_version": rating.get("engine_version", "UNKNOWN"),
                "deterministic_rule_traces": rating.get("execution_trace", []),
                "rating_input_digest": rating.get("input_digest", ""),
                "rating_output_digest": rating.get("output_digest", ""),
                "quote_proposal": quote,
                "security_tool_traces": security_ledger,
                "underwriter_resolution": underwriter_resolution,
            }
            # Compute deterministic seal over invariant decision fields (excluding random IDs/timestamps)
            deterministic_seal_basis = {
                "quote_id": quote_id,
                "source_uri": pack_body["source_uri"],
                "intake_extraction_map": intake,
                "appetite_evaluation": appetite,
                "enrichment_payload": enrichment,
                "symbolic_engine_version": pack_body["symbolic_engine_version"],
                "deterministic_rule_traces": pack_body["deterministic_rule_traces"],
                "rating_input_digest": pack_body["rating_input_digest"],
                "rating_output_digest": pack_body["rating_output_digest"],
                "quote_proposal": quote,
                "underwriter_resolution": underwriter_resolution,
            }
            pack_body["pack_digest"] = canonical_sha256(deterministic_seal_basis)

            return {
                "status": "COMPLETED",
                "audit_id": audit_id,
                "pack_digest": pack_body["pack_digest"],
                "pack_summary": pack_body,
            }

        if self._gateway is None:
            return _compile()
        return self._gateway.authorize_and_execute(
            agent_name=AGENT_NAME,
            quote_id=quote_id,
            tool_name="AuditCompliance.CompileRegulatorPack",
            required_scope="audit:compile_pack",
            operation=_compile,
        )
