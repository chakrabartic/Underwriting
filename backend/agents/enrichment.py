"""Subagent C: Data Enrichment Agent.

Integrates with external property and loss-history endpoints via Apigee, binding
every retrieved attribute to its exact API endpoint and JSON path citation.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.adapters import ApigeeHttpEnrichmentClient, SandboxEnrichmentClient
from backend.config import ExecutionMode
from backend.ports import EnrichmentClientPort
from backend.security import AgentGatewayProxy

logger = logging.getLogger(__name__)

AGENT_NAME = "DataEnrichmentAgent"


class DataEnrichmentAgent:
    """Fetches third-party property and claims telemetry with full citation provenance."""

    def __init__(
        self,
        apigee_endpoint: str = "https://api.apigee.example.com/enrichment",
        *,
        execution_mode: ExecutionMode = ExecutionMode.LOCAL_SANDBOX,
        client: EnrichmentClientPort | None = None,
        gateway: AgentGatewayProxy | None = None,
    ) -> None:
        self.apigee_endpoint = apigee_endpoint
        self._gateway = gateway
        if client is not None:
            self._client = client
        elif execution_mode == ExecutionMode.GCP_PRODUCTION:
            self._client = ApigeeHttpEnrichmentClient(apigee_endpoint=apigee_endpoint)
        else:
            self._client = SandboxEnrichmentClient(apigee_endpoint=apigee_endpoint)

    def fetch_enrichment_data(
        self, quote_id: str, extracted_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Retrieves grounded property characteristics and 5-year loss history."""
        logger.info("Fetching Apigee enrichment data for quote_id=%s", quote_id)

        def _fetch() -> dict[str, Any]:
            raw = self._client.fetch_property_and_loss_data(quote_id, extracted_data)
            return self._ensure_citation_uris(quote_id, raw)

        if self._gateway is None:
            enrichment_payload = _fetch()
        else:
            self._gateway.authorize_and_execute(
                agent_name=AGENT_NAME,
                quote_id=quote_id,
                tool_name="Apigee.PropertyLookup",
                required_scope="apigee:fetch_property",
                operation=lambda: True,
            )
            enrichment_payload = self._gateway.authorize_and_execute(
                agent_name=AGENT_NAME,
                quote_id=quote_id,
                tool_name="Apigee.ClaimsHistoryLookup",
                required_scope="apigee:fetch_claims",
                operation=_fetch,
            )

        return {
            "status": "COMPLETED",
            "enrichment_data": enrichment_payload,
        }

    @staticmethod
    def _ensure_citation_uris(
        quote_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Ensures every enriched attribute carries a canonical `apigee://` citation URI."""
        normalized: dict[str, Any] = {}
        for section, fields in payload.items():
            if not isinstance(fields, dict):
                normalized[section] = fields
                continue
            section_copy: dict[str, Any] = {}
            for field_name, item in fields.items():
                if not isinstance(item, dict):
                    section_copy[field_name] = item
                    continue
                trace = dict(item.get("grounding_trace", {}))
                endpoint = trace.get("endpoint", "/v1/enrichment")
                trace.setdefault("json_path", f"$.{section}.{field_name}")
                trace.setdefault(
                    "citation_uri", f"apigee://{quote_id}{endpoint}#{field_name}"
                )
                section_copy[field_name] = {
                    "value": item.get("value"),
                    "grounding_trace": trace,
                }
            normalized[section] = section_copy
        return normalized
