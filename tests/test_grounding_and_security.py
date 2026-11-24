"""Mechanical Grounding CI Gate & SPIFFE/Agent Gateway security tests."""

from __future__ import annotations

from dataclasses import replace
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from backend.adapters import GeminiInteractionsModelAdapter
from backend.agents.exposure import ExposureRiskSummaryAgent
from backend.compat import CallbackContext, validate_adk_callback_signature
from backend.grounding import (
    CitationRegistry,
    GroundingGateway,
    GroundingViolationError,
)
from backend.security import (
    AgentGatewayProxy,
    SpiffeIdentityProvider,
    ToolAuthorizationError,
)


def _sample_registry(quote_id: str = "QTE-GND-1") -> CitationRegistry:
    return CitationRegistry.from_workflow_artifacts(
        quote_id,
        intake_extracted_data={
            "business_name": {
                "value": "Acme Corp Logistics",
                "grounding_trace": {
                    "source": "DOC_AI",
                    "page": 1,
                    "citation_uri": f"docai://{quote_id}/page/1/business_name",
                },
            },
            "revenue": {
                "value": "$5,400,000",
                "grounding_trace": {
                    "source": "DOC_AI",
                    "page": 2,
                    "citation_uri": f"docai://{quote_id}/page/2/revenue",
                },
            },
        },
        enrichment_data={
            "property_characteristics": {
                "roof_age_years": {
                    "value": 22,
                    "grounding_trace": {
                        "source": "APIGEE_PROPERTY_DB",
                        "citation_uri": f"apigee://{quote_id}/v1/property#roof_age_years",
                    },
                }
            }
        },
    )


def test_grounding_gateway_accepts_valid_cited_assertions() -> None:
    """CI Gate: Properly cited assertions with exact attested numbers pass cleanly."""
    registry = _sample_registry("QTE-OK")
    gateway = GroundingGateway(strict_mode=True)

    report = gateway.validate_assertions(
        [
            {
                "claim_text": "Acme Corp Logistics reported revenue of $5,400,000.",
                "citation_uris": [
                    "docai://QTE-OK/page/1/business_name",
                    "docai://QTE-OK/page/2/revenue",
                ],
            },
            {
                "claim_text": "Property roof age is 22 years.",
                "citation_uris": ["apigee://QTE-OK/v1/property#roof_age_years"],
            },
        ],
        registry,
    )
    assert report.is_fully_grounded is True
    assert report.uncited_or_blocked_rate == 0.0
    assert len(report.verified_assertions) == 2


@pytest.mark.parametrize(
    ("bad_assertion", "expected_reason_fragment"),
    [
        (
            {"claim_text": "Uncited claim about flood zone.", "citation_uris": []},
            "uncited assertion blocked",
        ),
        (
            {
                "claim_text": "Fabricated source claim.",
                "citation_uris": ["docai://QTE-OK/page/99/nonexistent"],
            },
            "Unresolvable citation URI",
        ),
        (
            {
                # Subtle LLM numeric hallucination: cites real revenue URI, but invents $9,900,000!
                "claim_text": "Acme Corp Logistics reported revenue of $9,900,000.",
                "citation_uris": ["docai://QTE-OK/page/2/revenue"],
            },
            "Numeric hallucination blocked",
        ),
    ],
)
def test_grounding_gateway_blocks_uncited_fake_uri_and_numeric_hallucinations(
    bad_assertion: dict[str, Any], expected_reason_fragment: str
) -> None:
    """Verifies mechanical blocking of missing URIs, fake URIs, and altered numbers."""
    registry = _sample_registry("QTE-OK")
    strict_gateway = GroundingGateway(strict_mode=True)

    with pytest.raises(GroundingViolationError, match=expected_reason_fragment):
        strict_gateway.validate_assertions([bad_assertion], registry)


def test_exposure_agent_purges_partial_hallucination_in_runtime_mode() -> None:
    """Runtime mode purges an ungrounded assertion while preserving verified assertions."""

    class PartiallyHallucinatingModel:
        model_name = "mock-partial-hallucinator"

        def generate_structured_json(
            self, *, system_instruction: str, prompt: str, json_schema: dict[str, Any]
        ) -> str:
            del system_instruction, prompt, json_schema
            return json.dumps({
                "assertions": [
                    {
                        "claim_text": "Property roof age is 22 years.",
                        "citation_uris": ["apigee://QTE-MIX/v1/property#roof_age_years"],
                    },
                    {
                        "claim_text": "Invented earthquake fault within 2 miles.",
                        "citation_uris": ["apigee://QTE-MIX/v1/seismic#fault"],
                    },
                ]
            })

    registry = _sample_registry("QTE-MIX")
    agent = ExposureRiskSummaryAgent(llm_adapter=PartiallyHallucinatingModel())
    res = agent.synthesize("QTE-MIX", {}, {}, citation_registry=registry)

    assert len(res["assertions"]) == 1
    assert "22 years" in res["summary"]
    assert "earthquake" not in res["summary"]
    assert res["grounding_report"]["blocked_count"] == 1


def test_gemini_interactions_adapter_uses_current_interactions_api() -> None:
    """Verifies production adapter invokes `client.interactions.create` with `gemini-4-hydrogen`."""
    adapter = GeminiInteractionsModelAdapter(
        project_id="proj-1", location="us-central1", model="gemini-4-hydrogen"
    )
    mock_client = MagicMock()
    mock_interaction = MagicMock()
    mock_interaction.output_text = '{"assertions": []}'
    mock_client.interactions.create.return_value = mock_interaction
    adapter._client = mock_client

    out = adapter.generate_structured_json(
        system_instruction="sys",
        prompt="ctx",
        json_schema={"type": "object"},
    )
    assert out == '{"assertions": []}'
    mock_client.interactions.create.assert_called_once_with(
        model="gemini-4-hydrogen",
        system_instruction="sys",
        input="ctx",
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": {"type": "object"},
        },
    )


def test_spiffe_least_privilege_expiry_tampering_and_confused_deputy() -> None:
    """Verifies cryptographic, temporal, and scope isolation in SpiffeIdentityProvider."""
    now = 1_700_000_000.0
    idp = SpiffeIdentityProvider(ttl_seconds=60, clock=lambda: now)
    gateway = AgentGatewayProxy(idp)

    # 1. SymbolicRatingEngine is strictly forbidden from requesting GenAI or Apigee scopes
    with pytest.raises(ToolAuthorizationError, match="not permitted"):
        idp.mint_downscoped_token(
            agent_name="SymbolicRatingEngine",
            quote_id="QTE-1",
            requested_scopes={"genai:synthesize_summary"},
        )

    # 2. Valid token succeeds on bound quote
    token = idp.mint_downscoped_token(
        agent_name="IntakeClearanceAgent",
        quote_id="QTE-1",
        requested_scopes={"docai:extract_entities"},
    )
    assert (
        gateway.authorize_and_execute(
            agent_name="IntakeClearanceAgent",
            quote_id="QTE-1",
            tool_name="DocAI",
            required_scope="docai:extract_entities",
            operation=lambda: "ok",
            token=token,
        )
        == "ok"
    )

    # 3. Confused-deputy attack: replaying QTE-1 token against QTE-2 is blocked
    with pytest.raises(ToolAuthorizationError, match="Confused-deputy"):
        gateway.authorize_and_execute(
            agent_name="IntakeClearanceAgent",
            quote_id="QTE-2",
            tool_name="DocAI",
            required_scope="docai:extract_entities",
            operation=lambda: "never",
            token=token,
        )

    # 4. Tampered signature is blocked
    tampered = replace(token, quote_id="QTE-2")
    with pytest.raises(ToolAuthorizationError, match="signature"):
        idp.verify_token(
            tampered, expected_quote_id="QTE-2", required_scope="docai:extract_entities"
        )

    # 5. Expired token is blocked
    now += 120.0
    with pytest.raises(ToolAuthorizationError, match="Expired SPIFFE token"):
        idp.verify_token(
            token, expected_quote_id="QTE-1", required_scope="docai:extract_entities"
        )


def test_adk_callback_signature_enforcement() -> None:
    """Enforces Specification 07 keyword-only `callback_context` binding."""

    def valid_cb(*, callback_context: CallbackContext) -> None:
        del callback_context

    def invalid_positional(ctx: CallbackContext) -> None:
        del ctx

    validate_adk_callback_signature(valid_cb)
    with pytest.raises(TypeError, match="callback_context"):
        validate_adk_callback_signature(invalid_positional)
