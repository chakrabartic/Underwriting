"""Shared Epistemic Memory Layer & Quote Lifecycle State Machine.

Implements Specifications 00, 05, and 07:
1. Synchronizes `quote_id` dossiers with `session_id` scopes (Spec 07 Section 4).
2. Enforces legal `QuoteLifecycleState` transitions so no submission can become
   fragmented or orphaned—including automatic transition to `FAILED_QUARANTINED`
   upon unrecovered stage errors.
3. Maintains an append-only chronological `EpistemicMemoryNote` log enabling
   instant causal-chain inspection in the A2UI Referral Console.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Any

from backend.models import (
    EpistemicMemoryNote,
    QuoteLifecycleState,
    UnderwriterAction,
    UnderwriterResolution,
    VALID_STATE_TRANSITIONS,
    utc_now_iso,
)


class InvalidLifecycleTransitionError(ValueError):
    """Raised when attempting an illegal quote lifecycle state transition."""


class QuoteNotFoundError(KeyError):
    """Raised when querying a non-existent quote_id in Epistemic Memory."""


@dataclass
class QuoteDossier:
    """Mutable internal aggregate protected by `EpistemicMemoryStore`'s lock."""

    quote_id: str
    session_id: str
    source_uri: str
    intent: str
    state: QuoteLifecycleState = QuoteLifecycleState.INTAKE
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    state_history: list[dict[str, str]] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    citations: dict[str, dict[str, Any]] = field(default_factory=dict)
    memory_notes: list[EpistemicMemoryNote] = field(default_factory=list)
    error_detail: str | None = None

    def to_summary_dict(self) -> dict[str, Any]:
        intake_data = self.artifacts.get("intake", {}).get("extracted_data", {})
        rating_data = self.artifacts.get("rating", {})
        audit_data = self.artifacts.get("audit", {})
        return {
            "quote_id": self.quote_id,
            "session_id": self.session_id,
            "source_uri": self.source_uri,
            "state": self.state.value,
            "business_name": intake_data.get("business_name", {}).get(
                "value", "Pending Extraction"
            ),
            "adjusted_premium": rating_data.get("adjusted_premium"),
            "risk_score": rating_data.get("risk_score"),
            "decision": rating_data.get("decision"),
            "audit_id": audit_data.get("audit_id"),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error_detail": self.error_detail,
        }

    def to_full_dict(self) -> dict[str, Any]:
        return {
            **self.to_summary_dict(),
            "intent": self.intent,
            "state_history": list(self.state_history),
            "artifacts": dict(self.artifacts),
            "citations": dict(self.citations),
            "memory_notes": [
                note.model_dump(mode="json") for note in self.memory_notes
            ],
        }


class EpistemicMemoryStore:
    """Thread-safe Shared Epistemic Memory repository for quote lifecycles."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._dossiers: dict[str, QuoteDossier] = {}
        self._session_quotes: dict[str, list[str]] = {}

    def initialize_quote(
        self,
        *,
        quote_id: str,
        session_id: str,
        source_uri: str,
        intent: str,
    ) -> dict[str, Any]:
        """Registers a new quote in `INTAKE` state bound to `session_id`."""
        if not quote_id.strip() or not session_id.strip():
            raise ValueError("Both quote_id and session_id must be non-empty.")

        with self._lock:
            if quote_id in self._dossiers:
                raise ValueError(f"Quote {quote_id!r} already exists in memory.")
            now = utc_now_iso()
            dossier = QuoteDossier(
                quote_id=quote_id,
                session_id=session_id,
                source_uri=source_uri,
                intent=intent,
                state=QuoteLifecycleState.INTAKE,
                created_at=now,
                updated_at=now,
                state_history=[
                    {
                        "from_state": "NONE",
                        "to_state": QuoteLifecycleState.INTAKE.value,
                        "reason": "Submission received by Supervisor Orchestrator",
                        "timestamp": now,
                    }
                ],
            )
            dossier.memory_notes.append(
                EpistemicMemoryNote(
                    timestamp=now,
                    quote_id=quote_id,
                    session_id=session_id,
                    author="SupervisorAgentCore",
                    stage="INTAKE",
                    summary=f"Initialized quote lifecycle for {source_uri}.",
                    payload={"intent": intent, "source_uri": source_uri},
                )
            )
            self._dossiers[quote_id] = dossier
            self._session_quotes.setdefault(session_id, []).append(quote_id)
            return dossier.to_summary_dict()

    def transition_state(
        self,
        quote_id: str,
        target_state: QuoteLifecycleState,
        *,
        author: str,
        reason: str,
        artifact_key: str | None = None,
        artifact_payload: dict[str, Any] | None = None,
        error_detail: str | None = None,
    ) -> dict[str, Any]:
        """Atomically validates and applies a quote lifecycle state transition."""
        with self._lock:
            dossier = self._get_unlocked(quote_id)
            allowed = VALID_STATE_TRANSITIONS.get(dossier.state, frozenset())
            if target_state not in allowed:
                raise InvalidLifecycleTransitionError(
                    f"Illegal transition for quote {quote_id}: "
                    f"{dossier.state.value} -> {target_state.value}"
                )
            now = utc_now_iso()
            prev_state = dossier.state
            dossier.state = target_state
            dossier.updated_at = now
            if error_detail is not None:
                dossier.error_detail = error_detail
            if artifact_key and artifact_payload is not None:
                dossier.artifacts[artifact_key] = artifact_payload

            dossier.state_history.append({
                "from_state": prev_state.value,
                "to_state": target_state.value,
                "reason": reason,
                "timestamp": now,
            })
            dossier.memory_notes.append(
                EpistemicMemoryNote(
                    timestamp=now,
                    quote_id=quote_id,
                    session_id=dossier.session_id,
                    author=author,
                    stage=target_state.value,
                    summary=reason,
                    payload=artifact_payload or {},
                )
            )
            return dossier.to_summary_dict()

    def store_artifact(
        self,
        quote_id: str,
        *,
        artifact_key: str,
        artifact_payload: dict[str, Any],
        author: str,
        summary: str,
    ) -> None:
        """Stores an auxiliary artifact (such as the final Audit Pack) on a dossier."""
        with self._lock:
            dossier = self._get_unlocked(quote_id)
            now = utc_now_iso()
            dossier.updated_at = now
            dossier.artifacts[artifact_key] = artifact_payload
            dossier.memory_notes.append(
                EpistemicMemoryNote(
                    timestamp=now,
                    quote_id=quote_id,
                    session_id=dossier.session_id,
                    author=author,
                    stage=dossier.state.value,
                    summary=summary,
                    payload={"artifact_key": artifact_key},
                )
            )

    def set_citations(
        self, quote_id: str, citations: dict[str, dict[str, Any]]
    ) -> None:
        with self._lock:
            dossier = self._get_unlocked(quote_id)
            dossier.citations = dict(citations)

    def apply_underwriter_resolution(
        self,
        quote_id: str,
        resolution: UnderwriterResolution,
    ) -> dict[str, Any]:
        """Applies a human-in-the-loop underwriter action to a referred/STP quote."""
        target_map = {
            UnderwriterAction.APPROVE_BIND: QuoteLifecycleState.BOUND,
            UnderwriterAction.DECLINE: QuoteLifecycleState.DECLINED,
            UnderwriterAction.REQUEST_INFO: QuoteLifecycleState.INFO_REQUESTED,
        }
        target_state = target_map[resolution.action]
        resolution_dict = resolution.model_dump(mode="json")
        with self._lock:
            self.transition_state(
                quote_id,
                target_state,
                author=f"Underwriter:{resolution.underwriter_id}",
                reason=f"HITL Decision ({resolution.action.value}): {resolution.rationale}",
                artifact_key="underwriter_resolution",
                artifact_payload=resolution_dict,
            )
            return self._get_unlocked(quote_id).to_full_dict()

    def get_quote(self, quote_id: str) -> dict[str, Any]:
        with self._lock:
            return self._get_unlocked(quote_id).to_full_dict()

    def list_quotes(
        self,
        *,
        state: QuoteLifecycleState | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._dossiers.values())
            if state is not None:
                items = [d for d in items if d.state == state]
            if session_id is not None:
                items = [d for d in items if d.session_id == session_id]
            items.sort(key=lambda d: d.created_at, reverse=True)
            return [d.to_summary_dict() for d in items]

    def counts_by_state(self) -> dict[str, int]:
        with self._lock:
            counts = {s.value: 0 for s in QuoteLifecycleState}
            for dossier in self._dossiers.values():
                counts[dossier.state.value] += 1
            return counts

    def _get_unlocked(self, quote_id: str) -> QuoteDossier:
        dossier = self._dossiers.get(quote_id)
        if dossier is None:
            raise QuoteNotFoundError(f"Quote {quote_id!r} not found in Epistemic Memory.")
        return dossier
