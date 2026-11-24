"""Mechanical Grounding Gateway & Citation Registry (Specification 03 & 06).

Enforces the Zero-Tolerance Hallucination Policy architecturally rather than by
prompting alone:
1. Collects all authoritative evidence spans (`CitationRecord`) from Document AI
   bounding boxes, Apigee JSON paths, Appetite rules, and Symbolic Rating rules.
2. Intercepts natural-language assertions produced by neural/LLM agents before
   they can enter Shared Epistemic Memory or stream to the A2UI frontend.
3. Blocks or rejects any assertion that:
   - Lacks a citation URI,
   - References a non-existent or cross-quote citation URI, or
   - Contains numeric/currency quantities not attested by its cited evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from backend.models import GroundedAssertion


class GroundingViolationError(ValueError):
    """Raised when an agent output violates the mechanical grounding contract."""


# Strip benign version strings (e.g., v1.4.2) and rule identifiers (e.g., RATE_RULE_012)
# before extracting quantitative claims from prose.
_VERSION_OR_RULE_RE = re.compile(
    r"\bv\d+(?:\.\d+)+\b|\b[A-Z]+_RULE_\d+[A-Z0-9_]*\b"
)
_NUMERIC_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])\$?\d{1,3}(?:,\d{3})+(?:\.\d+)?|\$?\d+(?:\.\d+)?%?(?![A-Za-z0-9_])"
)


def extract_normalized_numbers(text: str) -> frozenset[Decimal]:
    """Extracts normalized Decimal quantities from natural language or raw strings."""
    sanitized = _VERSION_OR_RULE_RE.sub(" ", str(text))
    numbers: set[Decimal] = set()
    for match in _NUMERIC_TOKEN_RE.finditer(sanitized):
        token = match.group(0).replace("$", "").replace(",", "").replace("%", "").strip()
        if not token:
            continue
        try:
            numbers.add(Decimal(token).normalize())
        except InvalidOperation:
            continue
    return frozenset(numbers)


@dataclass(frozen=True, slots=True)
class CitationRecord:
    """Authoritative ground-truth evidence span registered for a specific quote."""

    citation_uri: str
    source_type: str
    label: str
    value: Any
    attested_numbers: frozenset[Decimal] = field(default_factory=frozenset)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_uri": self.citation_uri,
            "source_type": self.source_type,
            "label": self.label,
            "value": self.value,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class BlockedAssertionRecord:
    """Audit record describing why an ungrounded LLM assertion was purged."""

    claim_text: str
    citation_uris: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_text": self.claim_text,
            "citation_uris": list(self.citation_uris),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class GroundingValidationReport:
    """Result of passing agent assertions through the Mechanical Grounding Gateway."""

    verified_assertions: tuple[GroundedAssertion, ...]
    blocked_assertions: tuple[BlockedAssertionRecord, ...]

    @property
    def is_fully_grounded(self) -> bool:
        return len(self.blocked_assertions) == 0 and len(self.verified_assertions) > 0

    @property
    def uncited_or_blocked_rate(self) -> float:
        total = len(self.verified_assertions) + len(self.blocked_assertions)
        if total == 0:
            return 1.0
        return len(self.blocked_assertions) / total

    def render_summary_text(self) -> str:
        """Renders verified claims with inline citation tags for the A2UI workbench."""
        parts: list[str] = []
        for item in self.verified_assertions:
            refs = ", ".join(item.citation_uris)
            parts.append(f"{item.claim_text} [{refs}]")
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_fully_grounded": self.is_fully_grounded,
            "verified_count": len(self.verified_assertions),
            "blocked_count": len(self.blocked_assertions),
            "uncited_or_blocked_rate": self.uncited_or_blocked_rate,
            "verified_assertions": [
                a.model_dump(mode="json") for a in self.verified_assertions
            ],
            "blocked_assertions": [b.to_dict() for b in self.blocked_assertions],
        }


class CitationRegistry:
    """Per-quote registry of resolvable citations across Doc AI, Apigee, and Rules."""

    def __init__(self, quote_id: str) -> None:
        self.quote_id = quote_id
        self._records: dict[str, CitationRecord] = {}

    def register(
        self,
        *,
        citation_uri: str,
        source_type: str,
        label: str,
        value: Any,
        extra_numbers: set[Decimal] | frozenset[Decimal] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CitationRecord:
        nums = set(extract_normalized_numbers(str(value)))
        nums.update(extract_normalized_numbers(label))
        if extra_numbers:
            nums.update(d.normalize() for d in extra_numbers)
        record = CitationRecord(
            citation_uri=citation_uri,
            source_type=source_type,
            label=label,
            value=value,
            attested_numbers=frozenset(nums),
            metadata=metadata or {},
        )
        self._records[citation_uri] = record
        return record

    def get(self, citation_uri: str) -> CitationRecord | None:
        return self._records.get(citation_uri)

    def contains(self, citation_uri: str) -> bool:
        return citation_uri in self._records

    def all_records(self) -> dict[str, CitationRecord]:
        return dict(self._records)

    @classmethod
    def from_workflow_artifacts(
        cls,
        quote_id: str,
        *,
        intake_extracted_data: dict[str, Any],
        appetite_result: dict[str, Any] | None = None,
        enrichment_data: dict[str, Any] | None = None,
        rating_result: dict[str, Any] | None = None,
    ) -> CitationRegistry:
        """Builds a complete ground-truth CitationRegistry from upstream agent outputs."""
        registry = cls(quote_id=quote_id)

        for key, item in intake_extracted_data.items():
            trace = item.get("grounding_trace", {})
            uri = trace.get("citation_uri") or f"docai://{quote_id}/page/{trace.get('page', 1)}/{key}"
            registry.register(
                citation_uri=uri,
                source_type=trace.get("source", "DOC_AI"),
                label=key,
                value=item.get("value"),
                metadata=dict(trace),
            )

        if enrichment_data:
            for section, fields in enrichment_data.items():
                if not isinstance(fields, dict):
                    continue
                for field_name, item in fields.items():
                    trace = item.get("grounding_trace", {})
                    uri = (
                        trace.get("citation_uri")
                        or f"apigee://{quote_id}{trace.get('endpoint', '/v1/enrich')}#{field_name}"
                    )
                    extra: set[Decimal] = set()
                    if "5_years" in field_name:
                        extra.add(Decimal(5))
                    registry.register(
                        citation_uri=uri,
                        source_type=trace.get("source", "APIGEE"),
                        label=f"{section}.{field_name}",
                        value=item.get("value"),
                        extra_numbers=extra,
                        metadata=dict(trace),
                    )

        if appetite_result:
            decision = appetite_result.get("decision", "UNKNOWN")
            traces = appetite_result.get("rule_traces", [])
            if not traces:
                traces = ["APP_RULE_000_STANDARD_ELIGIBLE"]
            for rule_id in traces:
                uri = f"rule://appetite/{rule_id}"
                registry.register(
                    citation_uri=uri,
                    source_type="APPETITE_RULE",
                    label=rule_id,
                    value=decision,
                    metadata={"rule_id": rule_id, "decision": decision},
                )

        if rating_result:
            version = rating_result.get("engine_version", "v1.4.2")
            rating_nums: set[Decimal] = set()
            for num_key in ("base_premium", "adjusted_premium", "risk_score"):
                if rating_result.get(num_key) is not None:
                    rating_nums.add(Decimal(str(rating_result[num_key])).normalize())

            for rule_id in rating_result.get("execution_trace", []):
                uri = f"rule://rating/{version}/{rule_id}"
                registry.register(
                    citation_uri=uri,
                    source_type="RATING_RULE",
                    label=rule_id,
                    value={
                        "adjusted_premium": rating_result.get("adjusted_premium"),
                        "risk_score": rating_result.get("risk_score"),
                        "decision": rating_result.get("decision"),
                    },
                    extra_numbers=rating_nums,
                    metadata={"rule_id": rule_id, "engine_version": version},
                )
            for factor in rating_result.get("factors", []):
                factor_uri = factor.get("citation_uri")
                if factor_uri:
                    factor_nums = set(rating_nums)
                    factor_nums.add(Decimal(str(factor["impact"])).normalize())
                    registry.register(
                        citation_uri=factor_uri,
                        source_type="RATING_RULE",
                        label=factor.get("description", factor["rule_id"]),
                        value=factor["impact"],
                        extra_numbers=factor_nums,
                        metadata=dict(factor),
                    )

        return registry


class GroundingGateway:
    """Intercepts and mechanically validates agent assertions against a CitationRegistry."""

    def __init__(self, *, strict_mode: bool = False) -> None:
        self._strict_mode = strict_mode

    def validate_assertions(
        self,
        assertions: list[dict[str, Any] | GroundedAssertion],
        registry: CitationRegistry,
    ) -> GroundingValidationReport:
        """Validates every assertion's citation existence and numerical fidelity.

        In `strict_mode=True` (used for CI/CD groundedness gates), ANY ungrounded
        assertion immediately raises `GroundingViolationError`. In runtime mode,
        invalid assertions are purged and logged, and `GroundingViolationError` is
        raised if zero verified assertions remain.
        """
        verified: list[GroundedAssertion] = []
        blocked: list[BlockedAssertionRecord] = []

        for raw in assertions:
            if isinstance(raw, GroundedAssertion):
                claim_text = raw.claim_text.strip()
                uris = list(raw.citation_uris)
            elif isinstance(raw, dict):
                claim_text = str(raw.get("claim_text", "")).strip()
                raw_uris = raw.get("citation_uris")
                if raw_uris is None and raw.get("citation_uri"):
                    raw_uris = [raw["citation_uri"]]
                uris = [str(u).strip() for u in (raw_uris or []) if str(u).strip()]
            else:
                blocked.append(
                    BlockedAssertionRecord(
                        claim_text=repr(raw),
                        citation_uris=(),
                        reason="Malformed assertion payload type.",
                    )
                )
                continue

            if not claim_text:
                blocked.append(
                    BlockedAssertionRecord(
                        claim_text="",
                        citation_uris=tuple(uris),
                        reason="Empty claim_text.",
                    )
                )
                continue

            if not uris:
                blocked.append(
                    BlockedAssertionRecord(
                        claim_text=claim_text,
                        citation_uris=(),
                        reason="Missing citation_uris (uncited assertion blocked).",
                    )
                )
                continue

            missing_uris = [u for u in uris if not registry.contains(u)]
            if missing_uris:
                blocked.append(
                    BlockedAssertionRecord(
                        claim_text=claim_text,
                        citation_uris=tuple(uris),
                        reason=f"Unresolvable citation URI(s): {missing_uris}",
                    )
                )
                continue

            # Mechanical numerical consistency check: every quantity stated in prose
            # must be attested in the cited ground-truth records.
            claimed_numbers = extract_normalized_numbers(claim_text)
            if claimed_numbers:
                attested_union: set[Decimal] = set()
                for uri in uris:
                    rec = registry.get(uri)
                    if rec is not None:
                        attested_union.update(rec.attested_numbers)
                unattested = claimed_numbers - attested_union
                if unattested:
                    formatted = sorted(format(n, "f") for n in unattested)
                    blocked.append(
                        BlockedAssertionRecord(
                            claim_text=claim_text,
                            citation_uris=tuple(uris),
                            reason=(
                                "Numeric hallucination blocked; unattested quantity(ies) "
                                f"{formatted} not present in cited evidence {uris}."
                            ),
                        )
                    )
                    continue

            verified.append(
                GroundedAssertion(claim_text=claim_text, citation_uris=uris)
            )

        if self._strict_mode and blocked:
            reasons = "; ".join(f"{b.claim_text!r} -> {b.reason}" for b in blocked)
            raise GroundingViolationError(
                f"CI Groundedness Gate failed with {len(blocked)} violation(s): {reasons}"
            )

        if not verified:
            reasons = "; ".join(b.reason for b in blocked) or "No assertions generated."
            raise GroundingViolationError(
                f"All assertions blocked by GroundingGateway: {reasons}"
            )

        return GroundingValidationReport(
            verified_assertions=tuple(verified),
            blocked_assertions=tuple(blocked),
        )
