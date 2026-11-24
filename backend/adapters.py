"""Concrete sandbox and Google Cloud production adapters for domain ports.

Sandbox adapters provide zero-latency, deterministic execution across multiple
realistic underwriting submission profiles for local development and CI gates.
Production adapters encapsulate Document AI, BigQuery, Apigee HTTP, and the
modern Gemini Interactions API (`google-genai`).
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from google import genai
from google.cloud import bigquery
from google.cloud import documentai
import requests

from backend.models import RawDocumentEntity, utc_now_iso

logger = logging.getLogger(__name__)


# Realistic deterministic submission fixtures keyed by URI hints / scenario IDs.
_SCENARIO_DOCUMENTS: dict[str, list[dict[str, Any]]] = {
    "stp_retail": [
        {
            "type": "BUSINESS_NAME",
            "mention_text": "Harborview Books & Stationery LLC",
            "confidence": 0.99,
            "page": 1,
            "bounding_box": {"x": 96, "y": 140},
        },
        {
            "type": "PROPERTY_ADDRESS",
            "mention_text": "410 Oak Avenue, Evanston, IL 60201",
            "confidence": 0.97,
            "page": 1,
            "bounding_box": {"x": 96, "y": 188},
        },
        {
            "type": "REVENUE",
            "mention_text": "$1,250,000",
            "confidence": 0.96,
            "page": 2,
            "bounding_box": {"x": 280, "y": 420},
        },
        {
            "type": "OCCUPANCY_TYPE",
            "mention_text": "Retail Mercantile",
            "confidence": 0.95,
            "page": 2,
            "bounding_box": {"x": 280, "y": 465},
        },
    ],
    "decline_hazmat": [
        {
            "type": "BUSINESS_NAME",
            "mention_text": "Apex Pyrotechnics & HazMat Chemical Corp",
            "confidence": 0.98,
            "page": 1,
            "bounding_box": {"x": 102, "y": 144},
        },
        {
            "type": "PROPERTY_ADDRESS",
            "mention_text": "900 Refinery Road, Gary, IN 46402",
            "confidence": 0.96,
            "page": 1,
            "bounding_box": {"x": 102, "y": 195},
        },
        {
            "type": "REVENUE",
            "mention_text": "$18,500,000",
            "confidence": 0.94,
            "page": 2,
            "bounding_box": {"x": 300, "y": 448},
        },
        {
            "type": "OCCUPANCY_TYPE",
            "mention_text": "Hazardous Chemical Manufacturing",
            "confidence": 0.97,
            "page": 2,
            "bounding_box": {"x": 300, "y": 490},
        },
    ],
    "default_logistics": [
        {
            "type": "BUSINESS_NAME",
            "mention_text": "Acme Corp Logistics",
            "confidence": 0.98,
            "page": 1,
            "bounding_box": {"x": 100, "y": 150},
        },
        {
            "type": "PROPERTY_ADDRESS",
            "mention_text": "123 Industrial Way, Chicago, IL 60601",
            "confidence": 0.95,
            "page": 1,
            "bounding_box": {"x": 100, "y": 200},
        },
        {
            "type": "REVENUE",
            "mention_text": "$5,400,000",
            "confidence": 0.92,
            "page": 2,
            "bounding_box": {"x": 300, "y": 450},
        },
    ],
}


def resolve_scenario_key(uri_or_intent: str) -> str:
    """Maps a GCS URI or natural-language intent string to a deterministic scenario."""
    lowered = uri_or_intent.lower()
    if any(tok in lowered for tok in ("stp", "low-risk", "low_risk", "retail", "book")):
        return "stp_retail"
    if any(
        tok in lowered
        for tok in ("decline", "hazmat", "pyrotechnic", "chemical", "ineligible")
    ):
        return "decline_hazmat"
    return "default_logistics"


class SandboxDocumentExtractor:
    """Deterministic local Document AI simulator producing grounded coordinates."""

    def __init__(
        self, custom_entities_by_uri: dict[str, list[dict[str, Any]]] | None = None
    ) -> None:
        self._custom = custom_entities_by_uri or {}

    def extract_entities(
        self, gcs_uri: str, quote_id: str
    ) -> list[RawDocumentEntity]:
        if gcs_uri in self._custom:
            raw_items = self._custom[gcs_uri]
        else:
            scenario = resolve_scenario_key(gcs_uri)
            raw_items = _SCENARIO_DOCUMENTS[scenario]
        logger.info(
            "Sandbox Document AI extracted %d entities for quote=%s from uri=%s",
            len(raw_items),
            quote_id,
            gcs_uri,
        )
        return [RawDocumentEntity.model_validate(item) for item in raw_items]


class SandboxQuoteRepository:
    """Thread-safe in-memory BigQuery repository double for sandbox & CI runs."""

    def __init__(self, dataset_id: str = "quote_lifecycle_db") -> None:
        self.dataset_id = dataset_id
        self._lock = threading.Lock()
        self._rows: list[dict[str, Any]] = []

    @property
    def rows(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._rows)

    def register_quote(
        self, quote_id: str, gcs_uri: str, extracted_data: dict[str, Any]
    ) -> bool:
        row = {
            "quote_id": quote_id,
            "source_uri": gcs_uri,
            "status": "CLEARED",
            "extracted_data": extracted_data,
            "registered_at": utc_now_iso(),
        }
        with self._lock:
            self._rows.append(row)
        logger.info(
            "Registered quote=%s in sandbox dataset=%s", quote_id, self.dataset_id
        )
        return True


class SandboxEnrichmentClient:
    """Deterministic Apigee enrichment double returning cited risk attributes."""

    def __init__(
        self, apigee_endpoint: str = "https://api.apigee.example.com/enrichment"
    ) -> None:
        self.apigee_endpoint = apigee_endpoint

    def fetch_property_and_loss_data(
        self, quote_id: str, extracted_data: dict[str, Any]
    ) -> dict[str, Any]:
        business_name = (
            str(extracted_data.get("business_name", {}).get("value", "")).lower()
        )
        address = str(extracted_data.get("property_address", {}).get("value", ""))

        if "harborview" in business_name or "evanston" in address.lower():
            year_built, roof_age, construction = 2018, 6, "Fire Resistive"
            claims_count, total_incurred = 0, 0
        elif "pyrotechnics" in business_name or "hazmat" in business_name:
            year_built, roof_age, construction = 1974, 34, "Frame"
            claims_count, total_incurred = 4, 240000
        else:
            year_built, roof_age, construction = 1995, 22, "Masonry Non-Combustible"
            claims_count, total_incurred = 1, 15000

        return {
            "property_characteristics": {
                "year_built": {
                    "value": year_built,
                    "grounding_trace": {
                        "source": "APIGEE_PROPERTY_DB",
                        "endpoint": "/v1/property",
                        "json_path": "$.property_characteristics.year_built",
                        "citation_uri": (
                            f"apigee://{quote_id}/v1/property#year_built"
                        ),
                    },
                },
                "roof_age_years": {
                    "value": roof_age,
                    "grounding_trace": {
                        "source": "APIGEE_PROPERTY_DB",
                        "endpoint": "/v1/property",
                        "json_path": "$.property_characteristics.roof_age_years",
                        "citation_uri": (
                            f"apigee://{quote_id}/v1/property#roof_age_years"
                        ),
                    },
                },
                "construction_type": {
                    "value": construction,
                    "grounding_trace": {
                        "source": "APIGEE_PROPERTY_DB",
                        "endpoint": "/v1/property",
                        "json_path": "$.property_characteristics.construction_type",
                        "citation_uri": (
                            f"apigee://{quote_id}/v1/property#construction_type"
                        ),
                    },
                },
            },
            "loss_history": {
                "claims_last_5_years": {
                    "value": claims_count,
                    "grounding_trace": {
                        "source": "APIGEE_CLAIMS_DB",
                        "endpoint": "/v1/claims",
                        "json_path": "$.loss_history.claims_last_5_years",
                        "citation_uri": (
                            f"apigee://{quote_id}/v1/claims#claims_last_5_years"
                        ),
                    },
                },
                "total_incurred": {
                    "value": total_incurred,
                    "grounding_trace": {
                        "source": "APIGEE_CLAIMS_DB",
                        "endpoint": "/v1/claims",
                        "json_path": "$.loss_history.total_incurred",
                        "citation_uri": (
                            f"apigee://{quote_id}/v1/claims#total_incurred"
                        ),
                    },
                },
            },
        }


class DeterministicGroundedSynthesizer:
    """Offline LanguageModelPort synthesizer emitting 100% grounded JSON claims."""

    @property
    def model_name(self) -> str:
        return "deterministic-grounded-synthesizer-v1"

    def generate_structured_json(
        self,
        *,
        system_instruction: str,
        prompt: str,
        json_schema: dict[str, Any],
    ) -> str:
        del system_instruction, json_schema
        # Parse structured context embedded in the prompt.
        marker = "CONTEXT_JSON:\n"
        idx = prompt.find(marker)
        if idx == -1:
            raise ValueError("Prompt missing CONTEXT_JSON block for deterministic synthesis.")
        raw_context = prompt[idx + len(marker) :].strip()
        ctx = json.loads(raw_context)

        assertions: list[dict[str, Any]] = []
        intake = ctx.get("intake_data", {})
        enrichment = ctx.get("enrichment_data", {})
        rating = ctx.get("rating_data", {})
        appetite = ctx.get("appetite_data", {})

        biz = intake.get("business_name", {})
        rev = intake.get("revenue", {})
        if biz and rev:
            assertions.append({
                "claim_text": (
                    f"Applicant {biz['value']} reported annual revenue of {rev['value']}."
                ),
                "citation_uris": [
                    biz["grounding_trace"]["citation_uri"],
                    rev["grounding_trace"]["citation_uri"],
                ],
            })

        props = enrichment.get("property_characteristics", {})
        roof = props.get("roof_age_years", {})
        const_type = props.get("construction_type", {})
        if roof and const_type:
            assertions.append({
                "claim_text": (
                    f"Insured structure is {const_type['value']} construction with a "
                    f"roof age of {roof['value']} years."
                ),
                "citation_uris": [
                    const_type["grounding_trace"]["citation_uri"],
                    roof["grounding_trace"]["citation_uri"],
                ],
            })

        losses = enrichment.get("loss_history", {})
        claims = losses.get("claims_last_5_years", {})
        incurred = losses.get("total_incurred", {})
        if claims and incurred:
            incurred_val = int(incurred["value"])
            assertions.append({
                "claim_text": (
                    f"Five-year loss history reflects {claims['value']} claim(s) "
                    f"with ${incurred_val:,} total incurred."
                ),
                "citation_uris": [
                    claims["grounding_trace"]["citation_uri"],
                    incurred["grounding_trace"]["citation_uri"],
                ],
            })

        if appetite.get("decision") and appetite.get("rule_citation_uris"):
            assertions.append({
                "claim_text": (
                    f"Carrier appetite evaluation classified submission as "
                    f"{appetite['decision']}."
                ),
                "citation_uris": list(appetite["rule_citation_uris"]),
            })

        if rating.get("adjusted_premium") is not None and rating.get("rule_citation_uris"):
            prem = rating["adjusted_premium"]
            score = rating["risk_score"]
            decision = rating["decision"]
            assertions.append({
                "claim_text": (
                    f"Symbolic Rating Engine ({rating['engine_version']}) computed an "
                    f"adjusted premium of ${prem:,.2f} and risk score {score} ({decision})."
                ),
                "citation_uris": list(rating["rule_citation_uris"]),
            })

        return json.dumps({"assertions": assertions})


class GcpDocumentAiExtractor:
    """Production Google Cloud Document AI entity extractor."""

    def __init__(self, project_id: str, location: str, processor_id: str) -> None:
        self._project_id = project_id
        self._location = location
        self._processor_id = processor_id
        self._client: documentai.DocumentProcessorServiceClient | None = None
        self._lock = threading.Lock()

    def _get_client(self) -> documentai.DocumentProcessorServiceClient:
        with self._lock:
            if self._client is None:
                self._client = documentai.DocumentProcessorServiceClient()
            return self._client

    def extract_entities(
        self, gcs_uri: str, quote_id: str
    ) -> list[RawDocumentEntity]:
        client = self._get_client()
        name = client.processor_path(
            self._project_id, self._location, self._processor_id
        )
        request = documentai.ProcessRequest(
            name=name,
            gcs_document=documentai.GcsDocument(
                gcs_uri=gcs_uri, mime_type="application/pdf"
            ),
        )
        result = client.process_document(request=request)
        entities: list[RawDocumentEntity] = []
        for entity in result.document.entities:
            page_num = 1
            bbox = {"x": 0, "y": 0}
            if entity.page_anchor and entity.page_anchor.page_refs:
                ref = entity.page_anchor.page_refs[0]
                page_num = int(ref.page) + 1
                if ref.bounding_poly and ref.bounding_poly.normalized_vertices:
                    v0 = ref.bounding_poly.normalized_vertices[0]
                    bbox = {"x": int(v0.x * 1000), "y": int(v0.y * 1000)}
            entities.append(
                RawDocumentEntity(
                    type=entity.type_,
                    mention_text=entity.mention_text,
                    confidence=float(entity.confidence),
                    page=page_num,
                    bounding_box=bbox,
                )
            )
        logger.info(
            "Document AI extracted %d grounded entities for quote=%s",
            len(entities),
            quote_id,
        )
        return entities


class BigQueryQuoteRepository:
    """Production BigQuery repository persisting quote lifecycle registrations."""

    def __init__(self, project_id: str, dataset_id: str) -> None:
        self._project_id = project_id
        self._dataset_id = dataset_id
        self._client: bigquery.Client | None = None
        self._lock = threading.Lock()

    def _get_client(self) -> bigquery.Client:
        with self._lock:
            if self._client is None:
                self._client = bigquery.Client(project=self._project_id)
            return self._client

    def register_quote(
        self, quote_id: str, gcs_uri: str, extracted_data: dict[str, Any]
    ) -> bool:
        client = self._get_client()
        table_id = f"{self._project_id}.{self._dataset_id}.quotes"
        row = {
            "quote_id": quote_id,
            "source_uri": gcs_uri,
            "status": "CLEARED",
            "extracted_payload_json": json.dumps(extracted_data, sort_keys=True),
            "created_at": utc_now_iso(),
        }
        errors = client.insert_rows_json(table_id, [row])
        if errors:
            raise RuntimeError(f"BigQuery insert failed for quote {quote_id}: {errors}")
        return True


class ApigeeHttpEnrichmentClient:
    """Production Apigee API gateway client with explicit timeouts."""

    def __init__(self, apigee_endpoint: str, timeout_seconds: float = 10.0) -> None:
        self._endpoint = apigee_endpoint
        self._timeout = timeout_seconds

    def fetch_property_and_loss_data(
        self, quote_id: str, extracted_data: dict[str, Any]
    ) -> dict[str, Any]:
        response = requests.post(
            self._endpoint,
            json={"quote_id": quote_id, "extracted_data": extracted_data},
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return payload


class GeminiInteractionsModelAdapter:
    """Production Gemini adapter using the modern `client.interactions.create` API."""

    def __init__(
        self,
        project_id: str,
        location: str,
        model: str = "gemini-4-hydrogen",
    ) -> None:
        self._project_id = project_id
        self._location = location
        self._model = model
        self._client: genai.Client | None = None
        self._lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model

    def _get_client(self) -> genai.Client:
        with self._lock:
            if self._client is None:
                self._client = genai.Client(
                    enterprise=True,
                    project=self._project_id,
                    location=self._location,
                )
            return self._client

    def generate_structured_json(
        self,
        *,
        system_instruction: str,
        prompt: str,
        json_schema: dict[str, Any],
    ) -> str:
        client = self._get_client()
        interaction = client.interactions.create(
            model=self._model,
            system_instruction=system_instruction,
            input=prompt,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": json_schema,
            },
        )
        output_text = interaction.output_text
        if not output_text:
            raise RuntimeError(
                f"Gemini model {self._model!r} returned empty output_text."
            )
        return output_text
