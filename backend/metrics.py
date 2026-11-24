"""Thread-safe operational metrics registry for SLI/SLO observability.

Tracks throughput, outcome distributions (STP vs. Referral vs. Decline vs.
Quarantined Faults), Mechanical Grounding block rates, SPIFFE Gateway denials,
and per-stage execution latencies.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any


@dataclass
class StageLatencyStats:
    """Running latency accumulator for a named orchestration stage."""

    invocations: int = 0
    errors: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0

    def record(self, duration_ms: float, *, errored: bool = False) -> None:
        self.invocations += 1
        if errored:
            self.errors += 1
        self.total_ms += duration_ms
        if duration_ms > self.max_ms:
            self.max_ms = duration_ms

    def to_dict(self) -> dict[str, int | float]:
        avg = (self.total_ms / self.invocations) if self.invocations else 0.0
        return {
            "invocations": self.invocations,
            "errors": self.errors,
            "avg_ms": round(avg, 3),
            "max_ms": round(self.max_ms, 3),
            "total_ms": round(self.total_ms, 3),
        }


class OperationalMetricsRegistry:
    """In-process telemetry collector backing `/api/metrics`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._workflows_started = 0
        self._workflows_completed = 0
        self._workflows_failed = 0
        self._outcomes: dict[str, int] = {
            "QUOTED_STP": 0,
            "REFERRAL_QUEUE": 0,
            "DECLINED": 0,
        }
        self._grounded_assertions_verified = 0
        self._grounded_assertions_blocked = 0
        self._stage_latencies: dict[str, StageLatencyStats] = {}

    def record_workflow_start(self) -> None:
        with self._lock:
            self._workflows_started += 1

    def record_workflow_success(self, final_state: str) -> None:
        with self._lock:
            self._workflows_completed += 1
            self._outcomes[final_state] = self._outcomes.get(final_state, 0) + 1

    def record_workflow_failure(self) -> None:
        with self._lock:
            self._workflows_failed += 1

    def record_grounding_counts(self, *, verified: int, blocked: int) -> None:
        with self._lock:
            self._grounded_assertions_verified += verified
            self._grounded_assertions_blocked += blocked

    def record_stage_latency(
        self, stage_name: str, duration_ms: float, *, errored: bool = False
    ) -> None:
        with self._lock:
            stats = self._stage_latencies.setdefault(stage_name, StageLatencyStats())
            stats.record(duration_ms, errored=errored)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            failure_rate = (
                self._workflows_failed / self._workflows_started
                if self._workflows_started
                else 0.0
            )
            return {
                "workflows": {
                    "started": self._workflows_started,
                    "completed": self._workflows_completed,
                    "failed": self._workflows_failed,
                    "failure_rate": round(failure_rate, 6),
                    "outcomes": dict(self._outcomes),
                },
                "grounding_slo": {
                    "verified_assertions": self._grounded_assertions_verified,
                    "blocked_assertions": self._grounded_assertions_blocked,
                },
                "stage_latencies_ms": {
                    name: stats.to_dict()
                    for name, stats in sorted(self._stage_latencies.items())
                },
            }
