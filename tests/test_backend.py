"""
SYSTEM PATTERN: ISOLATED INTEGRATION & SCHEMA COMPLIANCE UNIT VALIDATION
Ensures multi-agent trace event emitters consistently map properties to structural JSON specifications.
"""

import json
import pytest
from backend.app import app  # Import app context safely inside sandbox testing modules

@pytest.fixture
def enterprise_client_test_harness():
    app.config['TESTING'] = True
    with app.test_client() as service_testing_harness:
        yield service_testing_harness

def test_stream_endpoint_schema_compliance(enterprise_client_test_harness):
    """Verifies that the streaming pipeline returns compliant content types and valid event blocks."""
    network_payload_target = {"prompt": "Run architectural validation analysis verify graph loops", "session_id": "sandbox-test-id-0"}
    network_response = enterprise_client_test_harness.post('/api/chat/stream', json=network_payload_target)
    
    assert network_response.status_code == 200
    assert "text/event-stream" in network_response.headers['Content-Type']
    
    # Process text chunks to verify parsing safety
    raw_response_text = network_response.get_data(as_text=True)
    first_emitted_line_item = raw_response_text.split('\n')[0]
    
    assert first_emitted_line_item.startswith("data:")
    
    # Strip standard data identifiers to inspect the underlying framework frame structure
    clean_json_string_payload = first_emitted_line_item.replace("data:", "").strip()
    parsed_json_rpc_data_block = json.loads(clean_json_string_payload)
    
    assert parsed_json_rpc_data_block["jsonrpc"] == "2.0"
    assert "method" in parsed_json_rpc_data_block
    assert "params" in parsed_json_rpc_data_block

