import pytest
from backend.agents.intake import IntakeClearanceAgent

def test_intake_agent_extraction():
    """Verifies the Intake Agent correctly parses Doc AI outputs and attaches grounding traces."""
    agent = IntakeClearanceAgent(
        project_id="test-project",
        location="us-central1",
        processor_id="test-processor",
        bq_dataset="test_dataset"
    )
    
    # Mock the GCS URI and Quote ID
    test_uri = "gs://underwriting-submissions/quote_001.pdf"
    test_quote_id = "quote-req-001"
    
    result = agent.process_submission(test_uri, test_quote_id)
    
    # Validate structured payload
    assert result["quote_id"] == test_quote_id
    assert result["status"] == "CLEARED"
    assert result["source_uri"] == test_uri
    
    # Validate mechanical grounding structure
    data = result["extracted_data"]
    
    assert "business_name" in data
    assert data["business_name"]["value"] == "Acme Corp Logistics"
    
    # Verify the trace exists for explainability
    trace = data["business_name"]["grounding_trace"]
    assert trace["source"] == "DOC_AI"
    assert trace["page"] == 1
    assert "bounding_box" in trace

