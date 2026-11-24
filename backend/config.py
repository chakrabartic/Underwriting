"""Centralized, immutable configuration for the Underwriting Workbench.

All runtime settings are resolved deterministically from environment variables
with safe local-sandbox defaults so unit and integration tests never trigger
implicit network or cloud metadata calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os


class ExecutionMode(StrEnum):
    """Controls whether external cloud adapters or hermetic sandbox adapters run."""

    LOCAL_SANDBOX = "local_sandbox"
    GCP_PRODUCTION = "gcp_production"


def _parse_origins(raw: str) -> tuple[str, ...]:
    origins = tuple(item.strip() for item in raw.split(",") if item.strip())
    return origins or ("http://localhost:5000", "http://127.0.0.1:5000")


def _parse_positive_int(raw: str, name: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Immutable application configuration validated at startup."""

    execution_mode: ExecutionMode = ExecutionMode.LOCAL_SANDBOX
    project_id: str = "chayan-genai-bb"
    location: str = "us-central1"
    docai_location: str = "us"
    docai_processor_id: str = "underwriting-docai-extractor"
    bq_dataset: str = "quote_lifecycle_db"
    submissions_bucket: str = "chayan-genai-bb-underwriting-submissions"
    quotes_bucket: str = "chayan-genai-bb-underwriting-quotes"
    apigee_endpoint: str = "https://api.apigee.example.com/enrichment"
    gemini_model: str = "gemini-4-hydrogen"
    rating_engine_version: str = "v1.4.2"
    spiffe_trust_domain: str = "underwriting.internal"
    token_ttl_seconds: int = 300
    cors_allowed_origins: tuple[str, ...] = (
        "http://localhost:5000",
        "http://127.0.0.1:5000",
    )
    host: str = "0.0.0.0"
    port: int = 5000

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise ValueError("project_id must not be empty.")
        if not self.gemini_model.strip():
            raise ValueError("gemini_model must not be empty.")
        if self.gemini_model.startswith(("gemini-1.5", "gemini-2.0", "gemini-2.5")):
            raise ValueError(
                f"Model {self.gemini_model!r} is deprecated; use 'gemini-4-hydrogen' "
                "or another current Gemini 4 model."
            )
        if self.token_ttl_seconds <= 0:
            raise ValueError("token_ttl_seconds must be greater than zero.")
        if not (1 <= self.port <= 65535):
            raise ValueError(f"port must be in 1..65535, got {self.port}.")

    @property
    def is_production(self) -> bool:
        """Returns True when configured to invoke live Google Cloud services."""
        return self.execution_mode == ExecutionMode.GCP_PRODUCTION

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> AppConfig:
        """Constructs validated configuration from an environment mapping."""
        env = os.environ if environ is None else environ
        raw_mode = env.get(
            "UNDERWRITING_EXECUTION_MODE", ExecutionMode.LOCAL_SANDBOX.value
        ).strip().lower()
        try:
            mode = ExecutionMode(raw_mode)
        except ValueError as exc:
            valid = ", ".join(m.value for m in ExecutionMode)
            raise ValueError(
                f"Invalid UNDERWRITING_EXECUTION_MODE={raw_mode!r}; expected one of: {valid}"
            ) from exc

        project_id = env.get("GOOGLE_CLOUD_PROJECT", "chayan-genai-bb").strip()
        return cls(
            execution_mode=mode,
            project_id=project_id,
            location=env.get("GOOGLE_CLOUD_LOCATION", "us-central1").strip(),
            docai_location=env.get("DOCAI_LOCATION", "us").strip(),
            docai_processor_id=env.get(
                "DOCAI_PROCESSOR_ID", "underwriting-docai-extractor"
            ).strip(),
            bq_dataset=env.get("BQ_DATASET", "quote_lifecycle_db").strip(),
            submissions_bucket=env.get(
                "SUBMISSIONS_BUCKET", f"{project_id}-underwriting-submissions"
            ).strip(),
            quotes_bucket=env.get(
                "QUOTES_BUCKET", f"{project_id}-underwriting-quotes"
            ).strip(),
            apigee_endpoint=env.get(
                "APIGEE_ENDPOINT", "https://api.apigee.example.com/enrichment"
            ).strip(),
            gemini_model=env.get("GEMINI_MODEL", "gemini-4-hydrogen").strip(),
            rating_engine_version=env.get("RATING_ENGINE_VERSION", "v1.4.2").strip(),
            spiffe_trust_domain=env.get(
                "SPIFFE_TRUST_DOMAIN", "underwriting.internal"
            ).strip(),
            token_ttl_seconds=_parse_positive_int(
                env.get("AGENT_TOKEN_TTL_SECONDS", "300"),
                name="AGENT_TOKEN_TTL_SECONDS",
            ),
            cors_allowed_origins=_parse_origins(
                env.get(
                    "CORS_ALLOWED_ORIGINS",
                    "http://localhost:5000,http://127.0.0.1:5000",
                )
            ),
            host=env.get("HOST", "0.0.0.0").strip(),
            port=_parse_positive_int(env.get("PORT", "5000"), name="PORT"),
        )
