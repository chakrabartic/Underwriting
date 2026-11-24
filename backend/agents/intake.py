"""Subagent A: Intake & Clearance Agent.

Ingests unstructured policy submissions from Cloud Storage, extracts mechanically
grounded entities (page + spatial bounding boxes) via Document AI, and registers
the cleared quote in the Quote Lifecycle repository.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from backend.adapters import (
    BigQueryQuoteRepository,
    GcpDocumentAiExtractor,
    SandboxDocumentExtractor,
    SandboxQuoteRepository,
)
from backend.config import ExecutionMode
from backend.models import GroundedValue, GroundingTrace, RawDocumentEntity
from backend.ports import DocumentExtractorPort, QuoteRepositoryPort
from backend.security import AgentGatewayProxy

logger = logging.getLogger(__name__)

AGENT_NAME = "IntakeClearanceAgent"


def validate_gcs_uri(gcs_uri: str) -> str:
    """Validates that `gcs_uri` is a well-formed `gs://<bucket>/<object>` URI."""
    cleaned = gcs_uri.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme != "gs" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError(
            f"Invalid Cloud Storage URI {gcs_uri!r}; expected 'gs://<bucket>/<object>'."
        )
    return cleaned


class IntakeClearanceAgent:
    """Purely extractive intake agent binding every entity to Doc AI coordinates."""

    def __init__(
        self,
        project_id: str = "chayan-genai-bb",
        location: str = "us-central1",
        processor_id: str = "underwriting-docai-extractor",
        bq_dataset: str = "quote_lifecycle_db",
        *,
        execution_mode: ExecutionMode = ExecutionMode.LOCAL_SANDBOX,
        extractor: DocumentExtractorPort | None = None,
        repository: QuoteRepositoryPort | None = None,
        gateway: AgentGatewayProxy | None = None,
    ) -> None:
        self.project_id = project_id
        self.location = location
        self.processor_id = processor_id
        self.bq_dataset = bq_dataset
        self._gateway = gateway

        if extractor is not None:
            self._extractor = extractor
        elif execution_mode == ExecutionMode.GCP_PRODUCTION:
            self._extractor = GcpDocumentAiExtractor(
                project_id=project_id, location="us", processor_id=processor_id
            )
        else:
            self._extractor = SandboxDocumentExtractor()

        if repository is not None:
            self._repository = repository
        elif execution_mode == ExecutionMode.GCP_PRODUCTION:
            self._repository = BigQueryQuoteRepository(
                project_id=project_id, dataset_id=bq_dataset
            )
        else:
            self._repository = SandboxQuoteRepository(dataset_id=bq_dataset)

    def process_submission(self, gcs_uri: str, quote_id: str) -> dict[str, Any]:
        """Extracts grounded entities from `gcs_uri` and registers `quote_id`."""
        normalized_uri = validate_gcs_uri(gcs_uri)
        if not quote_id or not quote_id.strip():
            raise ValueError("quote_id must be a non-empty identifier.")

        logger.info(
            "IntakeClearanceAgent started quote_id=%s source_uri=%s",
            quote_id,
            normalized_uri,
        )

        entities = self._run_tool(
            quote_id=quote_id,
            tool_name="DocumentAI.ProcessDocument",
            required_scope="docai:extract_entities",
            operation=lambda: self._extractor.extract_entities(normalized_uri, quote_id),
        )
        structured_data = self._parse_and_ground_entities(quote_id, entities)

        self._run_tool(
            quote_id=quote_id,
            tool_name="BigQuery.RegisterQuote",
            required_scope="bigquery:register_quote",
            operation=lambda: self._repository.register_quote(
                quote_id, normalized_uri, structured_data
            ),
        )

        return {
            "quote_id": quote_id,
            "status": "CLEARED",
            "extracted_data": structured_data,
            "source_uri": normalized_uri,
        }

    def _run_tool(
        self,
        *,
        quote_id: str,
        tool_name: str,
        required_scope: str,
        operation: Any,
    ) -> Any:
        if self._gateway is None:
            return operation()
        return self._gateway.authorize_and_execute(
            agent_name=AGENT_NAME,
            quote_id=quote_id,
            tool_name=tool_name,
            required_scope=required_scope,
            operation=operation,
        )

    @staticmethod
    def _parse_and_ground_entities(
        quote_id: str, doc_entities: list[RawDocumentEntity]
    ) -> dict[str, Any]:
        """Normalizes raw Document AI spans into canonical grounded fields."""
        structured_data: dict[str, Any] = {}
        for entity in doc_entities:
            key = entity.type.strip().lower()
            citation_uri = f"docai://{quote_id}/page/{entity.page}/{key}"
            grounded = GroundedValue(
                value=entity.mention_text,
                grounding_trace=GroundingTrace(
                    source="DOC_AI",
                    citation_uri=citation_uri,
                    page=entity.page,
                    bounding_box=dict(entity.bounding_box),
                    confidence=entity.confidence,
                ),
            )
            structured_data[key] = {
                "value": grounded.value,
                "grounding_trace": {
                    "source": "DOC_AI",
                    "citation_uri": citation_uri,
                    "page": entity.page,
                    "bounding_box": dict(entity.bounding_box),
                    "confidence": entity.confidence,
                },
            }
        return structured_data
