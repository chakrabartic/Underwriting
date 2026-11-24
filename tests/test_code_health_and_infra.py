"""Architectural governance, AST isolation, XSS prevention, and IaC policy tests."""

from __future__ import annotations

import ast
from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_symbolic_rating_engine_has_zero_llm_or_network_imports() -> None:
    """AST-verifies Spec 02: SymbolicRatingEngine must never import GenAI or HTTP clients."""
    rating_path = REPO_ROOT / "backend" / "agents" / "rating_engine.py"
    tree = ast.parse(rating_path.read_text(encoding="utf-8"), filename=str(rating_path))

    forbidden_prefixes = (
        "google.genai",
        "google.cloud",
        "vertexai",
        "openai",
        "anthropic",
        "requests",
        "httpx",
        "urllib",
        "aiohttp",
        "socket",
    )

    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    violations = [
        mod
        for mod in imported_modules
        if any(mod == p or mod.startswith(f"{p}.") for p in forbidden_prefixes)
    ]
    assert violations == [], f"SymbolicRatingEngine imported forbidden modules: {violations}"


def test_backend_free_of_deprecated_gemini_models_and_generate_content() -> None:
    """Ensures no backend Python module calls legacy `generate_content` or `gemini-2.5`."""
    backend_dir = REPO_ROOT / "backend"
    forbidden_pattern = re.compile(
        r"generate_content|GenerateContentConfig|gemini-1\.5|gemini-2\.0|gemini-2\.5"
    )
    offenders: list[str] = []

    for py_file in sorted(backend_dir.rglob("*.py")):
        if py_file.name == "config.py":
            # config.py explicitly rejects gemini-1.5/2.0/2.5 in validation
            content = py_file.read_text(encoding="utf-8")
            assert "generate_content" not in content
            continue
        text = py_file.read_text(encoding="utf-8")
        if forbidden_pattern.search(text):
            offenders.append(str(py_file.relative_to(REPO_ROOT)))

    assert offenders == [], f"Legacy Gemini API/model usage detected in: {offenders}"


def test_frontend_javascript_free_of_unsafe_innerhtml() -> None:
    """Prevents DOM XSS regressions by prohibiting `.innerHTML` in frontend JS."""
    js_path = REPO_ROOT / "frontend" / "static" / "js" / "app.js"
    source = js_path.read_text(encoding="utf-8")
    assert ".innerHTML" not in source
    assert "outerHTML" not in source


def test_terraform_security_and_service_completeness_invariants() -> None:
    """Verifies Terraform HCL enforces least-privilege IAM and provisions all 9 services."""
    main_tf = (REPO_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")

    # 1. All required cloud resource blocks exist
    required_resources = [
        'resource "google_storage_bucket" "submissions"',
        'resource "google_storage_bucket" "quotes"',
        'resource "google_document_ai_processor" "intake_extractor"',
        'resource "google_bigquery_dataset" "quote_lifecycle"',
        'resource "google_bigquery_table" "quotes"',
        'resource "google_bigquery_table" "audit_packs"',
        'resource "google_apigee_organization" "apigee_org"',
        'resource "google_looker_instance" "underwriting_semantic_layer"',
        'resource "google_container_cluster" "agent_mesh"',
        'resource "google_iam_workload_identity_pool" "spiffe_agent_pool"',
        'resource "google_cloud_run_v2_service" "agent_gateway"',
        'resource "google_cloud_run_v2_service" "symbolic_rating_engine"',
        'resource "google_cloud_run_v2_service" "orchestrator"',
    ]
    for block in required_resources:
        assert block in main_tf, f"Missing required Terraform resource: {block}"

    # 2. Hardened security invariants
    assert "force_destroy = true" not in main_tf
    assert 'ingress             = "INGRESS_TRAFFIC_ALL"' not in main_tf
    assert 'role    = "roles/storage.objectAdmin"' not in main_tf
    assert 'public_access_prevention    = "enforced"' in main_tf
    assert "uniform_bucket_level_access = true" in main_tf

    # 3. Balanced braces across all .tf files
    for tf_file in (REPO_ROOT / "infra").glob("*.tf"):
        txt = tf_file.read_text(encoding="utf-8")
        assert txt.count("{") == txt.count("}"), f"Unbalanced braces in {tf_file.name}"
