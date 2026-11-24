"""Domain models, state machine contracts, and typed schemas for Underwriting.

Every inter-agent boundary, citation trace, monetary value, and lifecycle state
transition is modeled with strict Pydantic v2 validation and deterministic
canonical hashing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


CENT = Decimal("0.01")


def quantize_money(amount: Decimal | int | float | str) -> Decimal:
    """Quantizes a monetary value to exact cents using banker-free ROUND_HALF_UP."""
    return Decimal(str(amount)).quantize(CENT, rounding=ROUND_HALF_UP)


def canonical_sha256(payload: Any) -> str:
    """Computes a deterministic SHA-256 hex digest over arbitrary JSON-compatible data."""
    def _default(obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return format(obj, "f")
        if isinstance(obj, BaseModel):
            return obj.model_dump(mode="json")
        if isinstance(obj, StrEnum):
            return obj.value
        raise TypeError(f"Object of type {type(obj).__name__} is not canonicalizable")

    serialized = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=_default
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def utc_now_iso() -> str:
    """Returns an ISO-8601 UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


class QuoteLifecycleState(StrEnum):
    """Comprehensive quote lifecycle states preventing orphaned submissions."""

    INTAKE = "INTAKE"
    CLEARED = "CLEARED"
    APPETITE_EVALUATED = "APPETITE_EVALUATED"
    ENRICHED = "ENRICHED"
    RATED = "RATED"
    SUMMARIZED = "SUMMARIZED"
    QUOTED_STP = "QUOTED_STP"
    REFERRAL_QUEUE = "REFERRAL_QUEUE"
    DECLINED = "DECLINED"
    BOUND = "BOUND"
    INFO_REQUESTED = "INFO_REQUESTED"
    FAILED_QUARANTINED = "FAILED_QUARANTINED"


VALID_STATE_TRANSITIONS: dict[QuoteLifecycleState, frozenset[QuoteLifecycleState]] = {
    QuoteLifecycleState.INTAKE: frozenset({
        QuoteLifecycleState.CLEARED,
        QuoteLifecycleState.FAILED_QUARANTINED,
    }),
    QuoteLifecycleState.CLEARED: frozenset({
        QuoteLifecycleState.APPETITE_EVALUATED,
        QuoteLifecycleState.FAILED_QUARANTINED,
    }),
    QuoteLifecycleState.APPETITE_EVALUATED: frozenset({
        QuoteLifecycleState.ENRICHED,
        QuoteLifecycleState.DECLINED,
        QuoteLifecycleState.FAILED_QUARANTINED,
    }),
    QuoteLifecycleState.ENRICHED: frozenset({
        QuoteLifecycleState.RATED,
        QuoteLifecycleState.FAILED_QUARANTINED,
    }),
    QuoteLifecycleState.RATED: frozenset({
        QuoteLifecycleState.SUMMARIZED,
        QuoteLifecycleState.FAILED_QUARANTINED,
    }),
    QuoteLifecycleState.SUMMARIZED: frozenset({
        QuoteLifecycleState.QUOTED_STP,
        QuoteLifecycleState.REFERRAL_QUEUE,
        QuoteLifecycleState.DECLINED,
        QuoteLifecycleState.FAILED_QUARANTINED,
    }),
    QuoteLifecycleState.QUOTED_STP: frozenset({
        QuoteLifecycleState.BOUND,
        QuoteLifecycleState.DECLINED,
    }),
    QuoteLifecycleState.REFERRAL_QUEUE: frozenset({
        QuoteLifecycleState.BOUND,
        QuoteLifecycleState.DECLINED,
        QuoteLifecycleState.INFO_REQUESTED,
    }),
    QuoteLifecycleState.INFO_REQUESTED: frozenset({
        QuoteLifecycleState.REFERRAL_QUEUE,
        QuoteLifecycleState.BOUND,
        QuoteLifecycleState.DECLINED,
    }),
    QuoteLifecycleState.BOUND: frozenset(),
    QuoteLifecycleState.DECLINED: frozenset(),
    QuoteLifecycleState.FAILED_QUARANTINED: frozenset(),
}


class AppetiteDecision(StrEnum):
    """Appetite eligibility outcomes bound to codified carrier appetite rules."""

    ELIGIBLE = "ELIGIBLE"
    REFERRAL = "REFERRAL"
    INELIGIBLE = "INELIGIBLE"


class RatingDecision(StrEnum):
    """Deterministic symbolic rating routing outcomes."""

    STP = "STP"
    REFERRAL = "REFERRAL"
    DECLINE = "DECLINE"


class UnderwriterAction(StrEnum):
    """Human-in-the-loop actions available in the Referral Console."""

    APPROVE_BIND = "APPROVE_BIND"
    DECLINE = "DECLINE"
    REQUEST_INFO = "REQUEST_INFO"


class BoundingBox(BaseModel):
    """Document AI spatial coordinate span on an extracted page."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(default=180, ge=0)
    height: int = Field(default=24, ge=0)


class GroundingTrace(BaseModel):
    """Evidence-binding metadata linking a value or rule to its authoritative source."""

    model_config = ConfigDict(frozen=True, extra="allow")

    source: str
    citation_uri: str
    page: int | None = Field(default=None, ge=1)
    bounding_box: BoundingBox | dict[str, int] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    endpoint: str | None = None
    json_path: str | None = None
    rule_id: str | None = None
    engine_version: str | None = None


class RawDocumentEntity(BaseModel):
    """Raw entity extracted from Document AI prior to canonical normalization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str
    mention_text: str
    confidence: float = Field(ge=0.0, le=1.0)
    page: int = Field(ge=1)
    bounding_box: dict[str, int]


class GroundedValue(BaseModel):
    """A single canonical field paired with its verifiable grounding trace."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: Any
    grounding_trace: GroundingTrace


class GroundedAssertion(BaseModel):
    """A natural-language claim bound to one or more resolvable citation URIs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_text: str = Field(min_length=1)
    citation_uris: list[str] = Field(min_length=1)

    @field_validator("citation_uris")
    @classmethod
    def _validate_non_empty_uris(cls, value: list[str]) -> list[str]:
        cleaned = [uri.strip() for uri in value if uri and uri.strip()]
        if not cleaned:
            raise ValueError("Every GroundedAssertion must cite at least one URI.")
        return cleaned


class StructuredExposureBriefingSchema(BaseModel):
    """Schema passed to Gemini Interactions API `response_format` for grounded output."""

    model_config = ConfigDict(extra="forbid")

    assertions: list[GroundedAssertion] = Field(
        description=(
            "List of concise, factual underwriting risk assertions. Every assertion "
            "must cite exact citation_uris from the provided Citation Registry and "
            "must never invent numbers or facts."
        )
    )


class RatingFactor(BaseModel):
    """Individual deterministic pricing modifier with rule and input provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str
    impact: Decimal
    rule_id: str
    citation_uri: str
    input_citation_uri: str | None = None
    grounding_reference: dict[str, Any] = Field(default_factory=dict)


class RatingResult(BaseModel):
    """Immutable deterministic output of the Symbolic Rating Engine."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["COMPLETED"] = "COMPLETED"
    base_premium: Decimal
    adjusted_premium: Decimal
    risk_score: Decimal
    decision: RatingDecision
    engine_version: str
    execution_trace: list[str]
    factors: list[RatingFactor]
    input_digest: str
    output_digest: str

    def to_legacy_dict(self) -> dict[str, Any]:
        """Serializes to backward-compatible JSON dictionary with exact numbers."""
        return {
            "status": self.status,
            "base_premium": float(self.base_premium),
            "adjusted_premium": float(self.adjusted_premium),
            "risk_score": float(self.risk_score),
            "decision": self.decision.value,
            "engine_version": self.engine_version,
            "execution_trace": list(self.execution_trace),
            "factors": [
                {
                    "description": factor.description,
                    "impact": float(factor.impact),
                    "rule_id": factor.rule_id,
                    "citation_uri": factor.citation_uri,
                    "input_citation_uri": factor.input_citation_uri,
                    "grounding_reference": dict(factor.grounding_reference),
                }
                for factor in self.factors
            ],
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
        }


class QuoteOption(BaseModel):
    """Single priced quote tier derived deterministically from adjusted_premium."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tier: str
    deductible: int = Field(ge=0)
    premium: Decimal
    multiplier: Decimal
    rule_id: str


class UnderwriterResolution(BaseModel):
    """Human-in-the-loop referral decision recorded by an authorized underwriter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: UnderwriterAction
    underwriter_id: str = Field(min_length=1, max_length=128)
    rationale: str = Field(min_length=5, max_length=2000)
    selected_tier: str | None = None
    resolved_at: str = Field(default_factory=utc_now_iso)


class EpistemicMemoryNote(BaseModel):
    """Immutable timestamped observation recorded in the Shared Epistemic Memory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: str = Field(default_factory=utc_now_iso)
    quote_id: str
    session_id: str
    author: str
    stage: str
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)


class JsonRpcFrame(BaseModel):
    """JSON-RPC 2.0 streaming notification frame emitted over SSE."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    jsonrpc: Literal["2.0"] = "2.0"
    method: str = Field(min_length=1)
    params: dict[str, Any]

    def encode(self) -> str:
        """Serializes frame to compact JSON string."""
        return self.model_dump_json()
