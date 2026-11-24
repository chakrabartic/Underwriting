terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.40"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  common_labels = {
    application = "underwriting-workbench"
    environment = var.environment
    managed_by  = "terraform"
  }

  resolved_orchestrator_image = (
    var.orchestrator_image != ""
    ? var.orchestrator_image
    : "us-docker.pkg.dev/${var.project_id}/underwriting/supervisor-orchestrator:latest"
  )

  resolved_rating_image = (
    var.rating_engine_image != ""
    ? var.rating_engine_image
    : "us-docker.pkg.dev/${var.project_id}/underwriting/symbolic-rating-engine:latest"
  )

  required_apis = toset([
    "storage.googleapis.com",
    "documentai.googleapis.com",
    "bigquery.googleapis.com",
    "apigee.googleapis.com",
    "looker.googleapis.com",
    "container.googleapis.com",
    "run.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "aiplatform.googleapis.com",
  ])
}

resource "google_project_service" "enabled_apis" {
  for_each           = local.required_apis
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# ==============================================================================
# 1. Cloud Storage — Intake Submissions & Outbound Proposals (Hardened)
# ==============================================================================
resource "google_storage_bucket" "submissions" {
  name                        = "${var.project_id}-underwriting-submissions"
  location                    = var.region
  force_destroy               = var.force_destroy_buckets
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.common_labels

  versioning {
    enabled = true
  }

  depends_on = [google_project_service.enabled_apis]
}

resource "google_storage_bucket" "quotes" {
  name                        = "${var.project_id}-underwriting-quotes"
  location                    = var.region
  force_destroy               = var.force_destroy_buckets
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.common_labels

  versioning {
    enabled = true
  }

  depends_on = [google_project_service.enabled_apis]
}

# ==============================================================================
# 2. Document AI — Mechanical Grounding Entity Extraction Processor
# ==============================================================================
resource "google_document_ai_processor" "intake_extractor" {
  location     = var.docai_location
  display_name = "underwriting-docai-extractor-${var.environment}"
  type         = "FORM_PARSER_PROCESSOR"

  depends_on = [google_project_service.enabled_apis]
}

# ==============================================================================
# 3. BigQuery — Centralized Quote Lifecycle & Regulatory Audit Warehouse
# ==============================================================================
resource "google_bigquery_dataset" "quote_lifecycle" {
  dataset_id                 = "quote_lifecycle_db"
  location                   = "US"
  description                = "Centralized quote lifecycle state store and regulator audit ledger"
  delete_contents_on_destroy = !var.enable_deletion_protection
  labels                     = local.common_labels

  depends_on = [google_project_service.enabled_apis]
}

resource "google_bigquery_table" "quotes" {
  dataset_id          = google_bigquery_dataset.quote_lifecycle.dataset_id
  table_id            = "quotes"
  deletion_protection = var.enable_deletion_protection
  labels              = local.common_labels

  time_partitioning {
    type  = "DAY"
    field = "created_at"
  }

  schema = jsonencode([
    { name = "quote_id", type = "STRING", mode = "REQUIRED" },
    { name = "source_uri", type = "STRING", mode = "REQUIRED" },
    { name = "status", type = "STRING", mode = "REQUIRED" },
    { name = "extracted_payload_json", type = "JSON", mode = "REQUIRED" },
    { name = "created_at", type = "TIMESTAMP", mode = "REQUIRED" }
  ])
}

resource "google_bigquery_table" "audit_packs" {
  dataset_id          = google_bigquery_dataset.quote_lifecycle.dataset_id
  table_id            = "audit_packs"
  deletion_protection = var.enable_deletion_protection
  labels              = local.common_labels

  time_partitioning {
    type  = "DAY"
    field = "generated_at"
  }

  schema = jsonencode([
    { name = "audit_id", type = "STRING", mode = "REQUIRED" },
    { name = "quote_id", type = "STRING", mode = "REQUIRED" },
    { name = "pack_digest", type = "STRING", mode = "REQUIRED" },
    { name = "symbolic_engine_version", type = "STRING", mode = "REQUIRED" },
    { name = "audit_payload_json", type = "JSON", mode = "REQUIRED" },
    { name = "generated_at", type = "TIMESTAMP", mode = "REQUIRED" }
  ])
}

# ==============================================================================
# 4. Apigee API Gateway — Third-Party Risk & Claims Data Enrichment
# ==============================================================================
resource "google_apigee_organization" "apigee_org" {
  analytics_region   = var.region
  project_id         = var.project_id
  authorized_network = "default"
  runtime_type       = "CLOUD"

  depends_on = [google_project_service.enabled_apis]
}

# ==============================================================================
# 5. Looker Core — Semantic Layer & Portfolio Risk Dashboards
# ==============================================================================
resource "google_looker_instance" "underwriting_semantic_layer" {
  name               = "underwriting-looker-${var.environment}"
  region             = var.region
  platform_edition   = "LOOKER_CORE_STANDARD"
  public_ip_enabled  = true

  oauth_config {
    client_id     = var.looker_oauth_client_id
    client_secret = var.looker_oauth_client_secret
  }

  depends_on = [google_project_service.enabled_apis]
}

# ==============================================================================
# 6. GKE — Stateful Agent Mesh Background Workers with Workload Identity
# ==============================================================================
resource "google_container_cluster" "agent_mesh" {
  name                = "underwriting-agent-mesh-${var.environment}"
  location            = var.region
  enable_autopilot    = true
  deletion_protection = var.enable_deletion_protection
  resource_labels     = local.common_labels

  release_channel {
    channel = "REGULAR"
  }

  depends_on = [google_project_service.enabled_apis]
}

# ==============================================================================
# 7, 8 & 9. Agent Identity (SPIFFE), Agent Gateway (Envoy), & Cloud Run Services
# ==============================================================================
resource "google_iam_workload_identity_pool" "spiffe_agent_pool" {
  workload_identity_pool_id = "underwriting-spiffe-${var.environment}"
  display_name              = "Underwriting SPIFFE Agent Identity Pool"
  description               = "Federates down-scoped SPIFFE SVID tokens for agent tool calls"

  depends_on = [google_project_service.enabled_apis]
}

resource "google_service_account" "orchestrator_identity" {
  account_id   = "uw-orchestrator-sa"
  display_name = "Supervisor Orchestrator Down-Scoped Identity"
}

# Isolated service account for Symbolic Rating Engine: ZERO Vertex AI / BigQuery / GCS roles.
resource "google_service_account" "symbolic_rating_identity" {
  account_id   = "uw-symbolic-rater-sa"
  display_name = "Symbolic Rating Engine Zero-LLM Isolated Identity"
}

resource "google_service_account" "agent_gateway_identity" {
  account_id   = "uw-agent-gateway-sa"
  display_name = "Envoy Agent Gateway Proxy Identity"
}

# Least-privilege resource-scoped IAM bindings (no project-wide admin grants)
resource "google_storage_bucket_iam_member" "orchestrator_submissions_reader" {
  bucket = google_storage_bucket.submissions.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.orchestrator_identity.email}"
}

resource "google_storage_bucket_iam_member" "orchestrator_quotes_writer" {
  bucket = google_storage_bucket.quotes.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.orchestrator_identity.email}"
}

resource "google_bigquery_dataset_iam_member" "orchestrator_dataset_editor" {
  dataset_id = google_bigquery_dataset.quote_lifecycle.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.orchestrator_identity.email}"
}

resource "google_project_iam_member" "orchestrator_docai_user" {
  project = var.project_id
  role    = "roles/documentai.apiUser"
  member  = "serviceAccount:${google_service_account.orchestrator_identity.email}"
}

resource "google_project_iam_member" "orchestrator_vertex_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.orchestrator_identity.email}"
}

# Isolated Cloud Run Service: Symbolic Rating Engine (Internal-Only Ingress)
resource "google_cloud_run_v2_service" "symbolic_rating_engine" {
  name                = "symbolic-rating-engine"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = var.enable_deletion_protection
  labels              = local.common_labels

  template {
    service_account = google_service_account.symbolic_rating_identity.email

    scaling {
      min_instance_count = 0
      max_instance_count = 20
    }

    containers {
      image = local.resolved_rating_image

      ports {
        container_port = 5000
      }

      env {
        name  = "UNDERWRITING_EXECUTION_MODE"
        value = "gcp_production"
      }

      env {
        name  = "RATING_ENGINE_VERSION"
        value = "v1.4.2"
      }

      startup_probe {
        http_get {
          path = "/readyz"
          port = 5000
        }
      }

      liveness_probe {
        http_get {
          path = "/healthz"
          port = 5000
        }
      }
    }
  }

  depends_on = [google_project_service.enabled_apis]
}

# Envoy-based Agent Gateway Proxy authorizing tool calls to downstream services
resource "google_cloud_run_v2_service" "agent_gateway" {
  name                = "agent-gateway-envoy"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = var.enable_deletion_protection
  labels              = local.common_labels

  template {
    service_account = google_service_account.agent_gateway_identity.email

    containers {
      image = var.envoy_gateway_image

      ports {
        container_port = 8080
      }
    }
  }

  depends_on = [google_project_service.enabled_apis]
}

# Allow only Agent Gateway and Orchestrator to invoke the Symbolic Rating Engine
resource "google_cloud_run_v2_service_iam_member" "gateway_invokes_rating_engine" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.symbolic_rating_engine.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.agent_gateway_identity.email}"
}

resource "google_cloud_run_v2_service_iam_member" "orchestrator_invokes_gateway" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.agent_gateway.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.orchestrator_identity.email}"
}

# Cloud Run Service: Supervisor Orchestrator & A2UI Streaming API
resource "google_cloud_run_v2_service" "orchestrator" {
  name                = "supervisor-orchestrator"
  location            = var.region
  ingress             = var.orchestrator_ingress
  deletion_protection = var.enable_deletion_protection
  labels              = local.common_labels

  template {
    service_account = google_service_account.orchestrator_identity.email

    scaling {
      min_instance_count = 1
      max_instance_count = 50
    }

    containers {
      image = local.resolved_orchestrator_image

      ports {
        container_port = 5000
      }

      env {
        name  = "UNDERWRITING_EXECUTION_MODE"
        value = "gcp_production"
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }

      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = var.region
      }

      env {
        name  = "DOCAI_PROCESSOR_ID"
        value = google_document_ai_processor.intake_extractor.id
      }

      env {
        name  = "BQ_DATASET"
        value = google_bigquery_dataset.quote_lifecycle.dataset_id
      }

      env {
        name  = "SUBMISSIONS_BUCKET"
        value = google_storage_bucket.submissions.name
      }

      env {
        name  = "QUOTES_BUCKET"
        value = google_storage_bucket.quotes.name
      }

      env {
        name  = "GEMINI_MODEL"
        value = "gemini-4-hydrogen"
      }

      startup_probe {
        http_get {
          path = "/readyz"
          port = 5000
        }
      }

      liveness_probe {
        http_get {
          path = "/healthz"
          port = 5000
        }
      }
    }
  }

  depends_on = [google_project_service.enabled_apis]
}
