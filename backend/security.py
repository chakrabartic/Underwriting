"""Agent Identity (SPIFFE) and Envoy-style Agent Gateway authorization layer.

Implements Specification 04:
1. Issues short-lived, HMAC-authenticated, down-scoped workload tokens per
   `(agent_name, quote_id, requested_scopes)` governed by an explicit least-privilege
   capability matrix.
2. Validates tokens and scope bindings prior to every tool execution, recording an
   immutable authorization ledger for regulatory audit packs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import hmac
import secrets
import threading
import time
from typing import TypeVar
import uuid

from backend.models import utc_now_iso

T = TypeVar("T")


class ToolAuthorizationError(PermissionError):
    """Raised when an agent attempts an unauthorized, cross-quote, or expired tool call."""


# Least-privilege capability matrix across all 7 domain subagents.
# Note: SymbolicRatingEngine intentionally possesses ZERO external network or GenAI scopes.
DEFAULT_AGENT_CAPABILITY_MATRIX: dict[str, frozenset[str]] = {
    "IntakeClearanceAgent": frozenset({
        "gcs:read_submission",
        "docai:extract_entities",
        "bigquery:register_quote",
    }),
    "AppetiteEligibilityAgent": frozenset({
        "rules:evaluate_appetite",
    }),
    "DataEnrichmentAgent": frozenset({
        "apigee:fetch_property",
        "apigee:fetch_claims",
    }),
    "SymbolicRatingEngine": frozenset({
        "rules:calculate_rating",
    }),
    "ExposureRiskSummaryAgent": frozenset({
        "genai:synthesize_summary",
    }),
    "QuoteGenerationAgent": frozenset({
        "gcs:write_quote_proposal",
    }),
    "AuditComplianceAgent": frozenset({
        "audit:compile_pack",
        "bigquery:write_audit",
    }),
}


@dataclass(frozen=True, slots=True)
class DownScopedSpiffeToken:
    """Ephemeral SPIFFE SVID-derived capability token bound to a single quote."""

    jti: str
    spiffe_id: str
    agent_name: str
    quote_id: str
    scopes: frozenset[str]
    issued_at: float
    expires_at: float
    signature: str

    def canonical_payload(self) -> str:
        sorted_scopes = ",".join(sorted(self.scopes))
        return (
            f"{self.jti}|{self.spiffe_id}|{self.agent_name}|{self.quote_id}|"
            f"{sorted_scopes}|{self.issued_at:.6f}|{self.expires_at:.6f}"
        )


@dataclass(frozen=True, slots=True)
class ToolAccessAuditEntry:
    """Immutable audit log entry produced by the Agent Gateway for every tool check."""

    timestamp: str
    jti: str
    spiffe_id: str
    agent_name: str
    quote_id: str
    tool_name: str
    required_scope: str
    authorized: bool
    reason: str

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "timestamp": self.timestamp,
            "jti": self.jti,
            "spiffe_id": self.spiffe_id,
            "agent_name": self.agent_name,
            "quote_id": self.quote_id,
            "tool_name": self.tool_name,
            "required_scope": self.required_scope,
            "authorized": self.authorized,
            "reason": self.reason,
        }


class SpiffeIdentityProvider:
    """Issues and cryptographically verifies down-scoped SPIFFE agent tokens."""

    def __init__(
        self,
        trust_domain: str = "underwriting.internal",
        ttl_seconds: int = 300,
        signing_key: bytes | None = None,
        capability_matrix: dict[str, frozenset[str]] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not trust_domain.strip():
            raise ValueError("trust_domain must not be empty.")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive.")
        self._trust_domain = trust_domain
        self._ttl_seconds = ttl_seconds
        self._signing_key = signing_key or secrets.token_bytes(32)
        self._matrix = capability_matrix or DEFAULT_AGENT_CAPABILITY_MATRIX
        self._clock = clock

    def _sign(self, payload: str) -> str:
        return hmac.new(
            self._signing_key, payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def mint_downscoped_token(
        self,
        *,
        agent_name: str,
        quote_id: str,
        requested_scopes: set[str] | frozenset[str],
    ) -> DownScopedSpiffeToken:
        """Mints a minimal-scope token if all requested scopes are allowed for the agent."""
        if not quote_id.strip():
            raise ToolAuthorizationError("quote_id is required for token down-scoping.")
        allowed = self._matrix.get(agent_name)
        if allowed is None:
            raise ToolAuthorizationError(
                f"Unknown agent identity {agent_name!r}; no SPIFFE workload registration."
            )
        scopes = frozenset(requested_scopes)
        if not scopes:
            raise ToolAuthorizationError("requested_scopes must not be empty.")
        unauthorized = scopes - allowed
        if unauthorized:
            raise ToolAuthorizationError(
                f"Agent {agent_name!r} is not permitted to request scope(s): "
                f"{sorted(unauthorized)}"
            )

        now = self._clock()
        jti = f"svid-{uuid.uuid4().hex[:12]}"
        spiffe_id = f"spiffe://{self._trust_domain}/ns/underwriting/sa/{agent_name}"
        unsigned = DownScopedSpiffeToken(
            jti=jti,
            spiffe_id=spiffe_id,
            agent_name=agent_name,
            quote_id=quote_id,
            scopes=scopes,
            issued_at=now,
            expires_at=now + self._ttl_seconds,
            signature="",
        )
        sig = self._sign(unsigned.canonical_payload())
        return DownScopedSpiffeToken(
            jti=unsigned.jti,
            spiffe_id=unsigned.spiffe_id,
            agent_name=unsigned.agent_name,
            quote_id=unsigned.quote_id,
            scopes=unsigned.scopes,
            issued_at=unsigned.issued_at,
            expires_at=unsigned.expires_at,
            signature=sig,
        )

    def verify_token(
        self,
        token: DownScopedSpiffeToken,
        *,
        expected_quote_id: str,
        required_scope: str,
    ) -> None:
        """Cryptographically validates signature, expiry, quote binding, and scope."""
        expected_sig = self._sign(token.canonical_payload())
        if not hmac.compare_digest(token.signature, expected_sig):
            raise ToolAuthorizationError("Invalid SPIFFE token cryptographic signature.")

        now = self._clock()
        if now > token.expires_at:
            raise ToolAuthorizationError(
                f"Expired SPIFFE token {token.jti} for agent {token.agent_name}."
            )
        if token.quote_id != expected_quote_id:
            raise ToolAuthorizationError(
                f"Confused-deputy violation: token bound to quote {token.quote_id!r}, "
                f"attempted execution on {expected_quote_id!r}."
            )
        if required_scope not in token.scopes:
            raise ToolAuthorizationError(
                f"Token {token.jti} lacks required scope {required_scope!r}."
            )


class AgentGatewayProxy:
    """Policy enforcement proxy authorizing and auditing all agent tool calls."""

    def __init__(self, identity_provider: SpiffeIdentityProvider) -> None:
        self._idp = identity_provider
        self._lock = threading.Lock()
        self._audit_entries: list[ToolAccessAuditEntry] = []

    @property
    def identity_provider(self) -> SpiffeIdentityProvider:
        return self._idp

    def get_audit_entries(self, quote_id: str | None = None) -> list[ToolAccessAuditEntry]:
        """Returns recorded gateway authorization events, optionally filtered by quote."""
        with self._lock:
            if quote_id is None:
                return list(self._audit_entries)
            return [e for e in self._audit_entries if e.quote_id == quote_id]

    def authorize_and_execute(
        self,
        *,
        agent_name: str,
        quote_id: str,
        tool_name: str,
        required_scope: str,
        operation: Callable[[], T],
        token: DownScopedSpiffeToken | None = None,
    ) -> T:
        """Authorizes a tool invocation via SPIFFE token and executes `operation`."""
        try:
            active_token = token or self._idp.mint_downscoped_token(
                agent_name=agent_name,
                quote_id=quote_id,
                requested_scopes={required_scope},
            )
            self._idp.verify_token(
                active_token,
                expected_quote_id=quote_id,
                required_scope=required_scope,
            )
        except ToolAuthorizationError as exc:
            entry = ToolAccessAuditEntry(
                timestamp=utc_now_iso(),
                jti=token.jti if token else "unissued",
                spiffe_id=(
                    token.spiffe_id if token else f"unverified:{agent_name}"
                ),
                agent_name=agent_name,
                quote_id=quote_id,
                tool_name=tool_name,
                required_scope=required_scope,
                authorized=False,
                reason=str(exc),
            )
            with self._lock:
                self._audit_entries.append(entry)
            raise

        entry = ToolAccessAuditEntry(
            timestamp=utc_now_iso(),
            jti=active_token.jti,
            spiffe_id=active_token.spiffe_id,
            agent_name=agent_name,
            quote_id=quote_id,
            tool_name=tool_name,
            required_scope=required_scope,
            authorized=True,
            reason="AUTHORIZED_OK",
        )
        with self._lock:
            self._audit_entries.append(entry)
        return operation()
