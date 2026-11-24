"""Integration, lifecycle, HITL referral, error-quarantine, and concurrency stress tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from typing import Any

import pytest

from backend.agents.enrichment import DataEnrichmentAgent
from backend.app import create_app
from backend.config import AppConfig
from backend.memory import EpistemicMemoryStore
from backend.metrics import OperationalMetricsRegistry
from backend.orchestrator import SupervisorOrchestratorEngine


def _parse_sse_frames(raw_sse_body: str) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for line in raw_sse_body.splitlines():
        if line.startswith("data:"):
            frames.append(json.loads(line.removeprefix("data:").strip()))
    return frames


@pytest.fixture
def enterprise_client_test_harness():
    test_app = create_app(AppConfig())
    test_app.config["TESTING"] = True
    with test_app.test_client() as client:
        yield client


def test_stream_endpoint_schema_compliance(enterprise_client_test_harness) -> None:
    """Verifies SSE headers, JSON-RPC 2.0 frame compliance, and security headers."""
    payload = {
        "prompt": "Evaluate commercial logistics submission for Acme Corp",
        "session_id": "sandbox-test-id-0",
    }
    response = enterprise_client_test_harness.post("/api/chat/stream", json=payload)

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["Content-Type"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"

    frames = _parse_sse_frames(response.get_data(as_text=True))
    assert len(frames) >= 8
    for frame in frames:
        assert frame["jsonrpc"] == "2.0"
        assert "method" in frame
        assert "params" in frame

    methods = [f["method"] for f in frames]
    assert methods[0] == "onAgentThought"
    assert "onUiComponentDelivery" in methods
    assert methods[-1] == "onWorkflowComplete"


@pytest.mark.parametrize(
    ("prompt", "expected_state", "expected_decision"),
    [
        ("Process low-risk retail bookstore STP submission", "QUOTED_STP", "STP"),
        ("Evaluate logistics warehouse submission", "REFERRAL_QUEUE", "REFERRAL"),
        ("Evaluate hazmat pyrotechnics chemical submission", "DECLINED", "DECLINE"),
    ],
)
def test_end_to_end_stp_referral_and_decline_lifecycles(
    enterprise_client_test_harness,
    prompt: str,
    expected_state: str,
    expected_decision: str,
) -> None:
    """Verifies all 3 canonical underwriting outcomes and audit pack completeness."""
    resp = enterprise_client_test_harness.post(
        "/api/chat/stream", json={"prompt": prompt, "session_id": "e2e-session"}
    )
    frames = _parse_sse_frames(resp.get_data(as_text=True))
    terminal = frames[-1]["params"]
    quote_id = terminal["quote_id"]

    assert terminal["lifecycle_state"] == expected_state
    assert terminal["decision"] == expected_decision

    # Verify Quote Dossier in Shared Epistemic Memory
    dossier_resp = enterprise_client_test_harness.get(f"/api/quotes/{quote_id}")
    assert dossier_resp.status_code == 200
    dossier = dossier_resp.get_json()
    assert dossier["state"] == expected_state
    assert len(dossier["memory_notes"]) >= 7

    # Verify Regulator-Ready Audit Pack export
    audit_resp = enterprise_client_test_harness.get(f"/api/quotes/{quote_id}/audit")
    assert audit_resp.status_code == 200
    audit = audit_resp.get_json()
    assert audit["audit_id"].startswith("AUDIT-")
    assert len(audit["pack_digest"]) == 64
    pack = audit["pack_summary"]
    assert pack["symbolic_engine_version"] == "v1.4.2"
    assert len(pack["deterministic_rule_traces"]) >= 1
    assert len(pack["security_tool_traces"]) >= 6


def test_hitl_referral_resolution_and_audit_resealing(
    enterprise_client_test_harness,
) -> None:
    """Verifies underwriter approval binds a referred quote, re-seals audit, and locks terminal state."""
    stream_resp = enterprise_client_test_harness.post(
        "/api/chat/stream",
        json={"prompt": "Acme Logistics submission", "session_id": "hitl-sess"},
    )
    quote_id = _parse_sse_frames(stream_resp.get_data(as_text=True))[-1]["params"]["quote_id"]
    initial_audit = enterprise_client_test_harness.get(f"/api/quotes/{quote_id}/audit").get_json()

    bind_resp = enterprise_client_test_harness.post(
        f"/api/quotes/{quote_id}/decision",
        json={
            "action": "APPROVE_BIND",
            "underwriter_id": "uw-lead-42",
            "rationale": "Verified updated roof inspection report; risk acceptable.",
            "selected_tier": "Standard",
        },
    )
    assert bind_resp.status_code == 200
    bound_dossier = bind_resp.get_json()
    assert bound_dossier["state"] == "BOUND"

    resealed_audit = enterprise_client_test_harness.get(f"/api/quotes/{quote_id}/audit").get_json()
    assert resealed_audit["pack_digest"] != initial_audit["pack_digest"]
    assert (
        resealed_audit["pack_summary"]["underwriter_resolution"]["underwriter_id"]
        == "uw-lead-42"
    )

    # Terminal BOUND state rejects conflicting subsequent transitions
    conflict_resp = enterprise_client_test_harness.post(
        f"/api/quotes/{quote_id}/decision",
        json={
            "action": "DECLINE",
            "underwriter_id": "uw-lead-42",
            "rationale": "Attempted post-bind reversal.",
        },
    )
    assert conflict_resp.status_code == 409


def test_fault_injection_quarantines_quote_without_orphaning() -> None:
    """Injects an upstream Apigee outage and verifies clean quarantine + error SSE frame."""

    class FailingEnrichmentClient:
        def fetch_property_and_loss_data(
            self, quote_id: str, extracted_data: dict[str, Any]
        ) -> dict[str, Any]:
            del quote_id, extracted_data
            raise ConnectionError("Apigee upstream 503 Service Unavailable")

    memory = EpistemicMemoryStore()
    metrics = OperationalMetricsRegistry()
    orchestrator = SupervisorOrchestratorEngine(
        session_id="fault-session",
        declarative_intent="Test fault isolation",
        quote_id="QTE-FAULT-01",
        memory_store=memory,
        metrics=metrics,
        enrichment_agent=DataEnrichmentAgent(client=FailingEnrichmentClient()),
    )

    frames = [json.loads(chunk) for chunk in orchestrator.execute_workflow()]
    assert frames[-1]["method"] == "onWorkflowError"
    assert frames[-1]["params"]["lifecycle_state"] == "FAILED_QUARANTINED"
    assert frames[-1]["params"]["error_type"] == "ConnectionError"

    dossier = memory.get_quote("QTE-FAULT-01")
    assert dossier["state"] == "FAILED_QUARANTINED"
    assert "Apigee upstream 503" in dossier["error_detail"]
    assert metrics.snapshot()["workflows"]["failed"] == 1


def test_isolated_rating_api_health_and_input_validation(
    enterprise_client_test_harness,
) -> None:
    """Tests `/healthz`, `/readyz`, `/api/metrics`, `/api/rating/calculate`, and 400 guards."""
    assert enterprise_client_test_harness.get("/healthz").status_code == 200
    ready = enterprise_client_test_harness.get("/readyz").get_json()
    assert ready["status"] == "ready"
    assert ready["gemini_model"] == "gemini-4-hydrogen"

    bad_stream = enterprise_client_test_harness.post(
        "/api/chat/stream", json={"gcs_uri": "http://not-gcs/file.pdf"}
    )
    assert bad_stream.status_code == 400

    rating_resp = enterprise_client_test_harness.post(
        "/api/rating/calculate",
        json={
            "quote_id": "QTE-API-RATE",
            "extracted_entities": {},
            "enrichment_data": {
                "property_characteristics": {
                    "roof_age_years": {"value": 10},
                    "construction_type": {"value": "Fire Resistive"},
                },
                "loss_history": {
                    "claims_last_5_years": {"value": 0},
                    "total_incurred": {"value": 0},
                },
            },
        },
    )
    assert rating_resp.status_code == 200
    rated = rating_resp.get_json()
    assert rated["adjusted_premium"] == 4500.0
    assert rated["decision"] == "STP"


def test_concurrent_multi_agent_orchestration_stress() -> None:
    """Stress-tests 24 concurrent workflow executions sharing memory and metrics."""
    memory = EpistemicMemoryStore()
    metrics = OperationalMetricsRegistry()
    config = AppConfig()
    prompts = [
        "Process low-risk retail bookstore STP submission",
        "Evaluate commercial logistics submission",
        "Evaluate hazmat pyrotechnics submission",
    ]

    def _run_one(idx: int) -> str:
        engine = SupervisorOrchestratorEngine(
            session_id=f"stress-sess-{idx % 4}",
            declarative_intent=prompts[idx % 3],
            quote_id=f"QTE-STRESS-{idx:03d}",
            config=config,
            memory_store=memory,
            metrics=metrics,
        )
        frames = [json.loads(c) for c in engine.execute_workflow()]
        assert frames[-1]["method"] == "onWorkflowComplete"
        return engine.quote_id

    with ThreadPoolExecutor(max_workers=8) as pool:
        quote_ids = list(pool.map(_run_one, range(24)))

    assert len(set(quote_ids)) == 24
    counts = memory.counts_by_state()
    assert counts["QUOTED_STP"] == 8
    assert counts["REFERRAL_QUEUE"] == 8
    assert counts["DECLINED"] == 8
    snap = metrics.snapshot()
    assert snap["workflows"]["completed"] == 24
    assert snap["workflows"]["failed"] == 0
