"""Hexagonal architecture port interfaces (Protocols) for external systems.

Decouples core domain agents from Google Cloud SDKs, Apigee HTTP transports, and
Gemini model endpoints so business logic is 100% deterministically testable
offline while seamlessly binding to production cloud adapters in deployment.
"""

from __future__ import annotations

from typing import Any, Protocol

from backend.models import RawDocumentEntity


class DocumentExtractorPort(Protocol):
    """Extracts grounded entities with page & bounding-box coordinates from PDFs."""

    def extract_entities(
        self, gcs_uri: str, quote_id: str
    ) -> list[RawDocumentEntity]: ...


class QuoteRepositoryPort(Protocol):
    """Persists quote intake and lifecycle state transitions (e.g., BigQuery)."""

    def register_quote(
        self, quote_id: str, gcs_uri: str, extracted_data: dict[str, Any]
    ) -> bool: ...


class EnrichmentClientPort(Protocol):
    """Fetches external property and loss-history risk data via Apigee."""

    def fetch_property_and_loss_data(
        self, quote_id: str, extracted_data: dict[str, Any]
    ) -> dict[str, Any]: ...


class LanguageModelPort(Protocol):
    """Generates structured natural-language briefings using Gemini Interactions API."""

    @property
    def model_name(self) -> str: ...

    def generate_structured_json(
        self,
        *,
        system_instruction: str,
        prompt: str,
        json_schema: dict[str, Any],
    ) -> str: ...
