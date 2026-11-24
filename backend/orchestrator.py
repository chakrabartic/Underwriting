"""Supervisor Orchestrator Engine coordinating the 7-subagent underwriting mesh.

Decouples workflow orchestration from HTTP/SSE transport while guaranteeing:
1. Non-orphaned quote lifecycle state tracking in Shared Epistemic Memory,
2. Down-scoped SPIFFE authorization via `AgentGatewayProxy` on every tool call,
3. Neuro-symbolic ordering (Symbolic Rating runs prior to Exposure Summary so
   LLM explanations cite deterministic `Rule_ID`s without owning any math),
4. Mechanical grounding verification on all neural outputs, and
5. Pattern-chaining safety: exceptions are caught, quarantined in memory, and
   emitted as structured JSON-RPC 2.0 error frames rather than breaking SSE.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
import logging
import time
from typing import Any
import uuid

from backend.adapters import resolve_scenario_key
from backend.agents.appetite import AppetiteEligibilityAgent
from backend.agents.audit import AuditComplianceAgent
from backend.agents.enrichment import DataEnrichmentAgent
from backend.agents.exposure import ExposureRiskSummaryAgent
from backend.agents.intake import IntakeClearanceAgent
from backend.agents.quote_gen import QuoteGenerationAgent
from backend.agents.rating_engine import SymbolicRatingEngine
from backend.compat import (
    AgentLifecycleCallback,
    CallbackContext,
    validate_adk_callback_signature,
)
from backend.config import AppConfig
from backend.grounding import CitationRegistry, GroundingGateway
from backend.memory import EpistemicMemoryStore
from backend.metrics import OperationalMetricsRegistry
from backend.models import JsonRpcFrame, QuoteLifecycleState, RatingDecision
from backend.security import AgentGatewayProxy, SpiffeIdentityProvider

logger = logging.getLogger(__name__)


def _default_gcs_uri_for_intent(submissions_bucket: str, intent: str) -> str:
    scenario = resolve_scenario_key(intent)
    filename_map = {
        "stp_retail": "harborview_retail_stp.pdf",
        "decline_hazmat": "apex_hazmat_decline.pdf",
        "default_logistics": "submission.pdf",
    }
    return f"gs://{submissions_bucket}/{filename_map[scenario]}"


class SupervisorOrchestratorEngine:
    """Centralized supervisor orchestrating underwriting subagents and SSE frames."""

    def __init__(
        self,
        session_id: str,
        declarative_intent: str,
        *,
        gcs_uri: str | None = None,
        quote_id: str | None = None,
        config: AppConfig | None = None,
        memory_store: EpistemicMemoryStore | None = None,
        gateway: AgentGatewayProxy | None = None,
        metrics: OperationalMetricsRegistry | None = None,
        intake_agent: IntakeClearanceAgent | None = None,
        appetite_agent: AppetiteEligibilityAgent | None = None,
        enrichment_agent: DataEnrichmentAgent | None = None,
        rating_engine: SymbolicRatingEngine | None = None,
        exposure_agent: ExposureRiskSummaryAgent | None = None,
        quote_agent: QuoteGenerationAgent | None = None,
        audit_agent: AuditComplianceAgent | None = None,
        before_agent_callbacks: list[AgentLifecycleCallback] | None = None,
        after_agent_callbacks: list[AgentLifecycleCallback] | None = None,
    ) -> None:
        self.session_id = session_id.strip() or "system-generated-durable-id"
        self.intent = declarative_intent.strip() or "Process commercial underwriting submission"
        self._config = config or AppConfig()
        self._memory = memory_store or EpistemicMemoryStore()
        self._gateway = gateway or AgentGatewayProxy(
            SpiffeIdentityProvider(
                trust_domain=self._config.spiffe_trust_domain,
                ttl_seconds=self._config.token_ttl_seconds,
            )
        )
        self._metrics = metrics or OperationalMetricsRegistry()
        self.quote_id = quote_id or f"QTE-{uuid.uuid4().hex[:8].upper()}"
        self.gcs_uri = gcs_uri or _default_gcs_uri_for_intent(
            self._config.submissions_bucket, self.intent
        )
        self.shared_context: dict[str, Any] = {
            "session_id": self.session_id,
            "quote_id": self.quote_id,
        }

        self._before_callbacks = list(before_agent_callbacks or [])
        self._after_callbacks = list(after_agent_callbacks or [])
        for cb in [*self._before_callbacks, *self._after_callbacks]:
            validate_adk_callback_signature(cb)

        self._intake_agent = intake_agent or IntakeClearanceAgent(
            project_id=self._config.project_id,
            location=self._config.location,
            processor_id=self._config.docai_processor_id,
            bq_dataset=self._config.bq_dataset,
            execution_mode=self._config.execution_mode,
            gateway=self._gateway,
        )
        self._appetite_agent = appetite_agent or AppetiteEligibilityAgent(
            gateway=self._gateway
        )
        self._enrichment_agent = enrichment_agent or DataEnrichmentAgent(
            apigee_endpoint=self._config.apigee_endpoint,
            execution_mode=self._config.execution_mode,
            gateway=self._gateway,
        )
        self._rating_engine = rating_engine or SymbolicRatingEngine(
            version=self._config.rating_engine_version,
            gateway=self._gateway,
        )
        self._exposure_agent = exposure_agent or ExposureRiskSummaryAgent(
            project_id=self._config.project_id,
            location=self._config.location,
            model=self._config.gemini_model,
            execution_mode=self._config.execution_mode,
            grounding_gateway=GroundingGateway(strict_mode=False),
            gateway=self._gateway,
        )
        self._quote_agent = quote_agent or QuoteGenerationAgent(
            quotes_bucket=self._config.quotes_bucket,
            gateway=self._gateway,
        )
        self._audit_agent = audit_agent or AuditComplianceAgent(
            gateway=self._gateway
        )

    def execute_workflow(self) -> Generator[str, None, None]:
        """Executes the full underwriting pipeline, yielding JSON-RPC 2.0 frames."""
        quote_id = self.quote_id
        self._metrics.record_workflow_start()
        self._memory.initialize_quote(
            quote_id=quote_id,
            session_id=self.session_id,
            source_uri=self.gcs_uri,
            intent=self.intent,
        )

        yield self._encode_rpc_frame(
            "onAgentThought",
            {
                "author": "SupervisorAgentCore",
                "quote_id": quote_id,
                "message": (
                    f"Orchestrating neuro-symbolic workflow for submission {quote_id} "
                    f"({self.gcs_uri})."
                ),
            },
        )

        try:
            # Stage 1: Document AI Intake & Clearance
            yield self._encode_rpc_frame(
                "onAgentDelegation",
                {
                    "author": "SupervisorAgentCore",
                    "target": "IntakeClearanceAgent",
                    "quote_id": quote_id,
                    "message": "Extracting grounded entities via Document AI & registering quote.",
                },
            )
            intake_res = self._invoke_stage(
                agent_name="IntakeClearanceAgent",
                stage="CLEARED",
                fn=lambda: self._intake_agent.process_submission(
                    self.gcs_uri, quote_id
                ),
            )
            self.shared_context["intake"] = intake_res
            self._memory.transition_state(
                quote_id,
                QuoteLifecycleState.CLEARED,
                author="IntakeClearanceAgent",
                reason="Document AI entities grounded and registered.",
                artifact_key="intake",
                artifact_payload=intake_res,
            )
            yield self._encode_rpc_frame(
                "onToolCall",
                {
                    "author": "IntakeClearanceAgent",
                    "tool": "DocumentAI.ProcessDocument + BigQuery.RegisterQuote",
                    "quote_id": quote_id,
                    "spiffe_authorized": True,
                },
            )

            # Stage 2: Carrier Appetite & Eligibility
            yield self._encode_rpc_frame(
                "onAgentDelegation",
                {
                    "author": "SupervisorAgentCore",
                    "target": "AppetiteEligibilityAgent",
                    "quote_id": quote_id,
                    "message": "Evaluating codified carrier appetite rules.",
                },
            )
            appetite_res = self._invoke_stage(
                agent_name="AppetiteEligibilityAgent",
                stage="APPETITE_EVALUATED",
                fn=lambda: self._appetite_agent.evaluate(
                    quote_id, intake_res["extracted_data"]
                ),
            )
            self.shared_context["appetite"] = appetite_res
            self._memory.transition_state(
                quote_id,
                QuoteLifecycleState.APPETITE_EVALUATED,
                author="AppetiteEligibilityAgent",
                reason=f"Appetite evaluated as {appetite_res['decision']}.",
                artifact_key="appetite",
                artifact_payload=appetite_res,
            )

            # Stage 3: External Risk Data Enrichment via Apigee
            yield self._encode_rpc_frame(
                "onAgentDelegation",
                {
                    "author": "SupervisorAgentCore",
                    "target": "DataEnrichmentAgent",
                    "quote_id": quote_id,
                    "message": "Fetching property & 5-year claims telemetry via Apigee.",
                },
            )
            enrich_res = self._invoke_stage(
                agent_name="DataEnrichmentAgent",
                stage="ENRICHED",
                fn=lambda: self._enrichment_agent.fetch_enrichment_data(
                    quote_id, intake_res["extracted_data"]
                ),
            )
            self.shared_context["enrichment"] = enrich_res
            self._memory.transition_state(
                quote_id,
                QuoteLifecycleState.ENRICHED,
                author="DataEnrichmentAgent",
                reason="External property and claims attributes enriched via Apigee.",
                artifact_key="enrichment",
                artifact_payload=enrich_res,
            )
            yield self._encode_rpc_frame(
                "onToolCall",
                {
                    "author": "DataEnrichmentAgent",
                    "tool": "Apigee.PropertyLookup + Apigee.ClaimsHistoryLookup",
                    "quote_id": quote_id,
                    "spiffe_authorized": True,
                },
            )

            # Stage 4: Deterministic Neuro-Symbolic Rating Engine (Zero-LLM)
            yield self._encode_rpc_frame(
                "onAgentDelegation",
                {
                    "author": "SupervisorAgentCore",
                    "target": "SymbolicRatingEngine",
                    "quote_id": quote_id,
                    "message": (
                        f"Executing deterministic pricing ({self._config.rating_engine_version})."
                    ),
                },
            )
            rating_res = self._invoke_stage(
                agent_name="SymbolicRatingEngine",
                stage="RATED",
                fn=lambda: self._rating_engine.calculate_premium(
                    quote_id,
                    intake_res["extracted_data"],
                    enrich_res["enrichment_data"],
                    appetite_decision=appetite_res["decision"],
                ),
            )
            self.shared_context["rating"] = rating_res
            self._memory.transition_state(
                quote_id,
                QuoteLifecycleState.RATED,
                author="SymbolicRatingEngine",
                reason=(
                    f"Rated ${rating_res['adjusted_premium']:,.2f} "
                    f"(score {rating_res['risk_score']}, {rating_res['decision']})."
                ),
                artifact_key="rating",
                artifact_payload=rating_res,
            )

            # Build complete CitationRegistry across Intake, Appetite, Enrichment, and Rating
            citation_registry = CitationRegistry.from_workflow_artifacts(
                quote_id,
                intake_extracted_data=intake_res["extracted_data"],
                appetite_result=appetite_res,
                enrichment_data=enrich_res["enrichment_data"],
                rating_result=rating_res,
            )
            citations_map = {
                uri: rec.to_dict()
                for uri, rec in citation_registry.all_records().items()
            }
            self._memory.set_citations(quote_id, citations_map)

            # Stage 5: Exposure & Risk Summary + Mechanical Grounding Gate
            yield self._encode_rpc_frame(
                "onAgentDelegation",
                {
                    "author": "SupervisorAgentCore",
                    "target": "ExposureRiskSummaryAgent",
                    "quote_id": quote_id,
                    "message": "Synthesizing briefing & verifying citations via GroundingGateway.",
                },
            )
            exposure_res = self._invoke_stage(
                agent_name="ExposureRiskSummaryAgent",
                stage="SUMMARIZED",
                fn=lambda: self._exposure_agent.synthesize(
                    quote_id,
                    intake_res["extracted_data"],
                    enrich_res["enrichment_data"],
                    appetite_data=appetite_res,
                    rating_data=rating_res,
                    citation_registry=citation_registry,
                ),
            )
            self.shared_context["exposure"] = exposure_res
            grounding_rep = exposure_res.get("grounding_report", {})
            self._metrics.record_grounding_counts(
                verified=int(grounding_rep.get("verified_count", 0)),
                blocked=int(grounding_rep.get("blocked_count", 0)),
            )
            self._memory.transition_state(
                quote_id,
                QuoteLifecycleState.SUMMARIZED,
                author="ExposureRiskSummaryAgent",
                reason="Risk summary mechanically verified against CitationRegistry.",
                artifact_key="exposure",
                artifact_payload=exposure_res,
            )

            # Stage 6: Multi-Tier Quote Generation & Lifecycle Routing (STP vs Referral vs Decline)
            yield self._encode_rpc_frame(
                "onAgentDelegation",
                {
                    "author": "SupervisorAgentCore",
                    "target": "QuoteGenerationAgent",
                    "quote_id": quote_id,
                    "message": "Compiling deterministic quote tiers and routing lifecycle.",
                },
            )
            quote_res = self._invoke_stage(
                agent_name="QuoteGenerationAgent",
                stage="QUOTED",
                fn=lambda: self._quote_agent.generate_quote_options(
                    quote_id, rating_res
                ),
            )
            self.shared_context["quote"] = quote_res

            routing_decision = rating_res["decision"]
            if routing_decision == RatingDecision.STP.value:
                final_state = QuoteLifecycleState.QUOTED_STP
                route_reason = "Low-risk quote routed to Straight-Through Processing (STP)."
            elif routing_decision == RatingDecision.DECLINE.value:
                final_state = QuoteLifecycleState.DECLINED
                route_reason = "Out-of-appetite / excessive-risk submission declined."
            else:
                final_state = QuoteLifecycleState.REFERRAL_QUEUE
                route_reason = "Submission routed to Underwriter Referral Queue for HITL review."

            self._memory.transition_state(
                quote_id,
                final_state,
                author="QuoteGenerationAgent",
                reason=route_reason,
                artifact_key="quote",
                artifact_payload=quote_res,
            )

            # Stage 7: Regulator-Ready Audit & Compliance Pack
            yield self._encode_rpc_frame(
                "onAgentDelegation",
                {
                    "author": "SupervisorAgentCore",
                    "target": "AuditComplianceAgent",
                    "quote_id": quote_id,
                    "message": "Sealing regulator-ready audit pack with SHA-256 digest.",
                },
            )
            audit_res = self._invoke_stage(
                agent_name="AuditComplianceAgent",
                stage="AUDITED",
                fn=lambda: self._audit_agent.build_audit_pack(
                    quote_id, self.shared_context
                ),
            )
            self.shared_context["audit"] = audit_res
            self._memory.store_artifact(
                quote_id,
                artifact_key="audit",
                artifact_payload=audit_res,
                author="AuditComplianceAgent",
                summary=f"Sealed regulatory audit pack {audit_res['audit_id']}.",
            )
            self._metrics.record_workflow_success(final_state.value)

            # Deliver declarative A2UI Workbench schema with full drill-down provenance
            yield self._encode_rpc_frame(
                "onUiComponentDelivery",
                self._build_ui_delivery_payload(
                    quote_id=quote_id,
                    final_state=final_state,
                    appetite_res=appetite_res,
                    exposure_res=exposure_res,
                    rating_res=rating_res,
                    quote_res=quote_res,
                    audit_res=audit_res,
                    citations_map=citations_map,
                ),
            )

            yield self._encode_rpc_frame(
                "onWorkflowComplete",
                {
                    "author": "SupervisorAgentCore",
                    "quote_id": quote_id,
                    "lifecycle_state": final_state.value,
                    "decision": routing_decision,
                    "audit_id": audit_res["audit_id"],
                },
            )

        except Exception as exc:
            logger.exception(
                "Workflow execution failed for quote_id=%s; quarantining quote.",
                quote_id,
            )
            self._metrics.record_workflow_failure()
            try:
                self._memory.transition_state(
                    quote_id,
                    QuoteLifecycleState.FAILED_QUARANTINED,
                    author="SupervisorAgentCore",
                    reason=f"Quarantined after error: {type(exc).__name__}",
                    error_detail=str(exc),
                )
            except Exception:
                logger.exception(
                    "Secondary error while quarantining quote_id=%s", quote_id
                )

            yield self._encode_rpc_frame(
                "onWorkflowError",
                {
                    "author": "SupervisorAgentCore",
                    "quote_id": quote_id,
                    "lifecycle_state": QuoteLifecycleState.FAILED_QUARANTINED.value,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            )

    def _invoke_stage(
        self,
        *,
        agent_name: str,
        stage: str,
        fn: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        ctx = CallbackContext(
            session_id=self.session_id,
            quote_id=self.quote_id,
            agent_name=agent_name,
            stage=stage,
        )
        for before_cb in self._before_callbacks:
            before_cb(callback_context=ctx)

        start = time.perf_counter()
        try:
            result = fn()
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self._metrics.record_stage_latency(agent_name, elapsed_ms, errored=True)
            raise

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self._metrics.record_stage_latency(agent_name, elapsed_ms, errored=False)

        for after_cb in self._after_callbacks:
            after_cb(callback_context=ctx)
        return result

    @staticmethod
    def _build_ui_delivery_payload(
        *,
        quote_id: str,
        final_state: QuoteLifecycleState,
        appetite_res: dict[str, Any],
        exposure_res: dict[str, Any],
        rating_res: dict[str, Any],
        quote_res: dict[str, Any],
        audit_res: dict[str, Any],
        citations_map: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        factor_rows = [
            [
                f["description"],
                f"${f['impact']:,.2f}",
                f["rule_id"],
                f.get("input_citation_uri") or f.get("citation_uri", ""),
            ]
            for f in rating_res.get("factors", [])
        ]
        quote_rows = [
            [
                opt["tier"],
                f"${opt['deductible']:,}",
                f"${opt['premium']:,.2f}",
                opt["rule_id"],
            ]
            for opt in quote_res.get("quote_options", [])
        ]

        return {
            "author": "SupervisorAgentCore",
            "ui_specification": "0.9",
            "quote_id": quote_id,
            "lifecycle_state": final_state.value,
            "citations": citations_map,
            "payload": {
                "type": "Tabs",
                "id": "agent_execution_summary_tabs",
                "quote_id": quote_id,
                "lifecycle_state": final_state.value,
                "decision": rating_res["decision"],
                "risk_score": rating_res["risk_score"],
                "adjusted_premium": rating_res["adjusted_premium"],
                "components": [
                    {
                        "title": "Risk Summary",
                        "type": "Card",
                        "content": exposure_res["summary"],
                        "assertions": exposure_res.get("assertions", []),
                        "appetite_decision": appetite_res["decision"],
                        "appetite_reasons": appetite_res.get("reasons", []),
                    },
                    {
                        "title": "Pricing & Factors",
                        "type": "Table",
                        "headers": [
                            "Factor",
                            "Impact",
                            "Rule ID",
                            "Evidence Citation",
                        ],
                        "rows": factor_rows,
                        "factors": rating_res.get("factors", []),
                        "base_premium": rating_res["base_premium"],
                        "adjusted_premium": rating_res["adjusted_premium"],
                        "risk_score": rating_res["risk_score"],
                    },
                    {
                        "title": "Quote Options",
                        "type": "Table",
                        "headers": ["Tier", "Deductible", "Annual Premium", "Rule ID"],
                        "rows": quote_rows,
                        "document_url": quote_res.get("document_url", ""),
                    },
                    {
                        "title": "Audit Trail",
                        "type": "Card",
                        "content": (
                            f"Audit ID: {audit_res['audit_id']} | "
                            f"Engine: {rating_res['engine_version']} | "
                            f"Pack SHA-256: {audit_res['pack_digest'][:16]}... | "
                            f"Rules: {', '.join(rating_res['execution_trace'])}"
                        ),
                        "audit_id": audit_res["audit_id"],
                        "pack_digest": audit_res["pack_digest"],
                    },
                ],
            },
        }

    @staticmethod
    def _encode_rpc_frame(method: str, params: dict[str, Any]) -> str:
        return JsonRpcFrame(method=method, params=params).encode()
