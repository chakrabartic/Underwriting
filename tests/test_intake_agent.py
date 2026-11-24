"""Unit and contract tests for Subagent A: IntakeClearanceAgent."""

from __future__ import annotations

import pytest

from backend.adapters import SandboxDocumentExtractor, SandboxQuoteRepository
from backend.agents.intake import IntakeClearanceAgent
from backend.security import AgentGatewayProxy, SpiffeIdentityProvider


def test_intake_agent_extraction() -> None:
    """Verifies Document AI entity normalization and coordinate citation binding."""
    repo = SandboxQuoteRepository(dataset_id="test_dataset")
    agent = IntakeClearanceAgent(
        project_id="test-project",
        location="us-central1",
        processor_id="test-processor",
        bq_dataset="test_dataset",
        repository=repo,
    )

    test_uri = "gs://underwriting-submissions/quote_001.pdf"
    test_quote_id = "quote-req-001"

    result = agent.process_submission(test_uri, test_quote_id)

    assert result["quote_id"] == test_quote_id
    assert result["status"] == "CLEARED"
    assert result["source_uri"] == test_uri
    assert len(repo.rows) == 1
    assert repo.rows[0]["quote_id"] == test_quote_id

    data = result["extracted_data"]
    assert "business_name" in data
    assert data["business_name"]["value"] == "Acme Corp Logistics"

    trace = data["business_name"]["grounding_trace"]
    assert trace["source"] == "DOC_AI"
    assert trace["page"] == 1
    assert trace["bounding_box"] == {"x": 100, "y": 150}
    assert trace["citation_uri"] == "docai://quote-req-001/page/1/business_name"


@pytest.mark.parametrize(
    "invalid_uri",
    [
        "",
        "https://storage.googleapis.com/bucket/file.pdf",
        "gs://bucket-only",
        "gs:///missing-bucket.pdf",
        "file:///etc/passwd",
    ],
)
def test_intake_rejects_invalid_gcs_uris(invalid_uri: str) -> None:
    """Ensures non-gs:// or malformed URIs fail fast before invoking downstream tools."""
    agent = IntakeClearanceAgent()
    with pytest.raises(ValueError, match="Invalid Cloud Storage URI"):
        agent.process_submission(invalid_uri, "QTE-INVALID")


def test_intake_records_spiffe_gateway_authorizations() -> None:
    """Verifies that Document AI and BigQuery tool calls pass through AgentGatewayProxy."""
    gateway = AgentGatewayProxy(SpiffeIdentityProvider())
    extractor = SandboxDocumentExtractor()
    agent = IntakeClearanceAgent(extractor=extractor, gateway=gateway)

    agent.process_submission("gs://submissions/stp_retail.pdf", "QTE-SPIFFE-01")
    entries = gateway.get_audit_entries("QTE-SPIFFE-01")

    assert len(entries) == 2
    assert all(e.authorized for e in entries)
    assert {e.required_scope for e in entries} == {
        "docai:extract_entities",
        "bigquery:register_quote",
    }
