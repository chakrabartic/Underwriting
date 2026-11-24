"""Flask application factory, REST endpoints, and SSE streaming controller.

Exposes:
- `GET /`: A2UI Explainable Underwriting Workbench
- `GET /healthz`, `GET /readyz`: Cloud Run & GKE health probes
- `GET /api/metrics`: Operational SLI/SLO telemetry snapshot
- `GET /api/session`: Session bootstrap metadata
- `POST|GET /api/chat/stream`: Real-time JSON-RPC 2.0 SSE orchestration stream
- `POST /api/rating/calculate`: Isolated deterministic Symbolic Rating API (Spec 02)
- `GET /api/quotes`: Quote Lifecycle Dashboard feed (Spec 05)
- `GET /api/quotes/<quote_id>`: Shared Epistemic Memory dossier & citations
- `GET /api/quotes/<quote_id>/audit`: Regulator-Ready Audit Pack export (Spec 03)
- `POST /api/quotes/<quote_id>/decision`: Human-in-the-loop Referral Console resolution
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any
import uuid

from flask import Flask, Response, jsonify, render_template, request
from flask_cors import CORS
from pydantic import ValidationError

from backend.agents.audit import AuditComplianceAgent
from backend.agents.intake import validate_gcs_uri
from backend.agents.rating_engine import SymbolicRatingEngine
from backend.compat import stabilize_a2a_runtime
from backend.config import AppConfig
from backend.memory import (
    EpistemicMemoryStore,
    InvalidLifecycleTransitionError,
    QuoteNotFoundError,
)
from backend.metrics import OperationalMetricsRegistry
from backend.models import QuoteLifecycleState, UnderwriterResolution
from backend.orchestrator import SupervisorOrchestratorEngine
from backend.security import AgentGatewayProxy, SpiffeIdentityProvider

MAX_PROMPT_LENGTH = 4000
MAX_SESSION_ID_LENGTH = 128

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def create_app(
    config: AppConfig | None = None,
    *,
    memory_store: EpistemicMemoryStore | None = None,
    metrics: OperationalMetricsRegistry | None = None,
    gateway: AgentGatewayProxy | None = None,
) -> Flask:
    """Application factory creating a hermetic, dependency-injected Flask app."""
    resolved_config = config or AppConfig.from_env()
    runtime_compat_status = stabilize_a2a_runtime()

    shared_memory = memory_store or EpistemicMemoryStore()
    shared_metrics = metrics or OperationalMetricsRegistry()
    shared_gateway = gateway or AgentGatewayProxy(
        SpiffeIdentityProvider(
            trust_domain=resolved_config.spiffe_trust_domain,
            ttl_seconds=resolved_config.token_ttl_seconds,
        )
    )

    flask_app = Flask(
        __name__,
        static_folder=str(_FRONTEND_DIR / "static"),
        template_folder=str(_FRONTEND_DIR / "templates"),
    )
    flask_app.config["UNDERWRITING_CONFIG"] = resolved_config
    flask_app.extensions["epistemic_memory"] = shared_memory
    flask_app.extensions["operational_metrics"] = shared_metrics
    flask_app.extensions["agent_gateway"] = shared_gateway

    CORS(
        flask_app,
        resources={
            r"/api/*": {"origins": list(resolved_config.cors_allowed_origins)}
        },
    )

    @flask_app.after_request
    def _apply_security_headers(response: Response) -> Response:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        return response

    @flask_app.route("/", methods=["GET"])
    def index() -> str:
        return render_template("index.html")

    @flask_app.route("/healthz", methods=["GET"])
    def healthz() -> tuple[Response, int]:
        return jsonify({"status": "ok"}), 200

    @flask_app.route("/readyz", methods=["GET"])
    def readyz() -> tuple[Response, int]:
        return (
            jsonify({
                "status": "ready",
                "execution_mode": resolved_config.execution_mode.value,
                "rating_engine_version": resolved_config.rating_engine_version,
                "gemini_model": resolved_config.gemini_model,
                "runtime_compat": runtime_compat_status,
            }),
            200,
        )

    @flask_app.route("/api/session", methods=["GET"])
    def session_context_manager() -> tuple[Response, int]:
        return (
            jsonify({
                "session_id": f"sess-{uuid.uuid4().hex[:12]}",
                "lifecycle_state": "ACTIVE",
                "ttl": resolved_config.token_ttl_seconds,
            }),
            200,
        )

    @flask_app.route("/api/metrics", methods=["GET"])
    def metrics_endpoint() -> tuple[Response, int]:
        return (
            jsonify({
                **shared_metrics.snapshot(),
                "quotes_by_state": shared_memory.counts_by_state(),
                "gateway_authorized_calls": len([
                    e for e in shared_gateway.get_audit_entries() if e.authorized
                ]),
                "gateway_denied_calls": len([
                    e for e in shared_gateway.get_audit_entries() if not e.authorized
                ]),
            }),
            200,
        )

    @flask_app.route("/api/chat/stream", methods=["POST", "GET"])
    def reactive_stream_endpoint() -> Response | tuple[Response, int]:
        if request.method == "POST":
            payload = request.get_json(silent=True)
            if payload is None:
                payload = {}
            if not isinstance(payload, dict):
                return jsonify({"error": "JSON request body must be an object."}), 400
            prompt = str(
                payload.get("prompt", "Execute commercial underwriting workflow")
            )
            session_id = str(
                payload.get("session_id", "system-generated-durable-id")
            )
            raw_gcs_uri = payload.get("gcs_uri")
        else:
            prompt = request.args.get(
                "prompt", "Execute commercial underwriting workflow"
            )
            session_id = request.args.get(
                "session_id", "system-generated-durable-id"
            )
            raw_gcs_uri = request.args.get("gcs_uri")

        if len(prompt) > MAX_PROMPT_LENGTH:
            return (
                jsonify({
                    "error": f"prompt exceeds maximum length of {MAX_PROMPT_LENGTH}."
                }),
                400,
            )
        if len(session_id) > MAX_SESSION_ID_LENGTH:
            return (
                jsonify({
                    "error": (
                        f"session_id exceeds maximum length of {MAX_SESSION_ID_LENGTH}."
                    )
                }),
                400,
            )

        validated_uri: str | None = None
        if raw_gcs_uri:
            try:
                validated_uri = validate_gcs_uri(str(raw_gcs_uri))
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400

        orchestrator = SupervisorOrchestratorEngine(
            session_id=session_id,
            declarative_intent=prompt,
            gcs_uri=validated_uri,
            config=resolved_config,
            memory_store=shared_memory,
            gateway=shared_gateway,
            metrics=shared_metrics,
        )

        def sse_event_encoder() -> Generator[str, None, None]:
            for trace_chunk in orchestrator.execute_workflow():
                yield f"data: {trace_chunk}\n\n"

        return Response(
            sse_event_encoder(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @flask_app.route("/api/rating/calculate", methods=["POST"])
    def symbolic_rating_endpoint() -> tuple[Response, int]:
        """Isolated REST API for the deterministic Symbolic Rating Engine (Spec 02)."""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Expected JSON object payload."}), 400

        quote_id = str(payload.get("quote_id", "")).strip()
        extracted_entities = payload.get("extracted_entities")
        enrichment_data = payload.get("enrichment_data")
        rule_version = str(
            payload.get("rule_version", resolved_config.rating_engine_version)
        ).strip()
        appetite_decision = payload.get("appetite_decision")

        if not quote_id:
            return jsonify({"error": "quote_id is required."}), 400
        if not isinstance(extracted_entities, dict) or not isinstance(
            enrichment_data, dict
        ):
            return (
                jsonify({
                    "error": (
                        "extracted_entities and enrichment_data must be JSON objects."
                    )
                }),
                400,
            )

        try:
            engine = SymbolicRatingEngine(
                version=rule_version, gateway=shared_gateway
            )
            result = engine.calculate_premium(
                quote_id=quote_id,
                extracted_data=extracted_entities,
                enrichment_data=enrichment_data,
                appetite_decision=(
                    str(appetite_decision) if appetite_decision else None
                ),
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        return jsonify(result), 200

    @flask_app.route("/api/quotes", methods=["GET"])
    def list_quotes_endpoint() -> tuple[Response, int]:
        raw_state = request.args.get("state")
        session_id = request.args.get("session_id")
        state_filter: QuoteLifecycleState | None = None
        if raw_state:
            try:
                state_filter = QuoteLifecycleState(raw_state.upper())
            except ValueError:
                return jsonify({"error": f"Unknown quote state: {raw_state!r}"}), 400

        quotes = shared_memory.list_quotes(
            state=state_filter, session_id=session_id
        )
        return (
            jsonify({
                "quotes": quotes,
                "counts_by_state": shared_memory.counts_by_state(),
            }),
            200,
        )

    @flask_app.route("/api/quotes/<quote_id>", methods=["GET"])
    def get_quote_endpoint(quote_id: str) -> tuple[Response, int]:
        try:
            dossier = shared_memory.get_quote(quote_id)
        except QuoteNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        return jsonify(dossier), 200

    @flask_app.route("/api/quotes/<quote_id>/audit", methods=["GET"])
    def export_audit_pack_endpoint(quote_id: str) -> tuple[Response, int]:
        try:
            dossier = shared_memory.get_quote(quote_id)
        except QuoteNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404

        audit_artifact = dossier.get("artifacts", {}).get("audit")
        if not audit_artifact:
            return (
                jsonify({"error": f"Audit pack not yet generated for {quote_id}."}),
                409,
            )
        return jsonify(audit_artifact), 200

    @flask_app.route("/api/quotes/<quote_id>/decision", methods=["POST"])
    def resolve_referral_endpoint(quote_id: str) -> tuple[Response, int]:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Expected JSON object payload."}), 400

        try:
            resolution = UnderwriterResolution.model_validate(payload)
        except ValidationError as exc:
            return jsonify({"error": "Invalid decision payload.", "details": exc.errors()}), 400

        try:
            updated_dossier = shared_memory.apply_underwriter_resolution(
                quote_id, resolution
            )
        except QuoteNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except InvalidLifecycleTransitionError as exc:
            return jsonify({"error": str(exc)}), 409

        # Re-seal the regulatory audit pack so the underwriter's decision is captured
        artifacts: dict[str, Any] = dict(updated_dossier.get("artifacts", {}))
        audit_agent = AuditComplianceAgent(gateway=shared_gateway)
        refreshed_audit = audit_agent.build_audit_pack(quote_id, artifacts)
        shared_memory.store_artifact(
            quote_id,
            artifact_key="audit",
            artifact_payload=refreshed_audit,
            author="AuditComplianceAgent",
            summary=(
                f"Re-sealed audit pack {refreshed_audit['audit_id']} following "
                f"underwriter {resolution.action.value}."
            ),
        )
        return jsonify(shared_memory.get_quote(quote_id)), 200

    return flask_app


# Default WSGI application instance preserving `from backend.app import app` compatibility.
app = create_app()

__all__ = ["SupervisorOrchestratorEngine", "app", "create_app"]


if __name__ == "__main__":
    cfg = app.config["UNDERWRITING_CONFIG"]
    app.run(host=cfg.host, port=cfg.port, debug=False)
