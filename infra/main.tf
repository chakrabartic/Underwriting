terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# 1. Cloud Storage - Intake Submissions & Quotes
resource "google_storage_bucket" "submissions" {
  name          = "${var.project_id}-underwriting-submissions"
  location      = var.region
  force_destroy = true
}

resource "google_storage_bucket" "quotes" {
  name          = "${var.project_id}-underwriting-quotes"
  location      = var.region
  force_destroy = true
}

# 2. Document AI - Extraction Processor
resource "google_document_ai_processor" "intake_extractor" {
  location     = "us"
  display_name = "underwriting-docai-extractor"
  type         = "INVOICE_PROCESSOR" # Using generic built-in for illustration
}

# 3. BigQuery - Quote Lifecycle Database
resource "google_bigquery_dataset" "quote_lifecycle" {
  dataset_id  = "quote_lifecycle_db"
  location    = "US"
  description = "Centralized quote tracking to prevent orphaned records"
}

# 4. Apigee API Gateway - External Data Enrichment
# Note: Full Apigee provisioning is complex; placeholder representing the gateway.
resource "google_apigee_organization" "apigee_org" {
  analytics_region   = var.region
  project_id         = var.project_id
  authorized_network = "default"
}

# 5. Looker - Semantic Layer (Placeholder for Looker instance)
# Note: Looker Core provisioning
# resource "google_looker_instance" "looker" { ... }

# 6. GKE - Container Deployment for Agent Mesh Background Workers
resource "google_container_cluster" "primary" {
  name               = "underwriting-agent-mesh"
  location           = var.region
  initial_node_count = 1
  deletion_protection = false

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }
}

# 7. Cloud Run - Stateless Agent Functions & API
resource "google_cloud_run_v2_service" "orchestrator" {
  name     = "supervisor-orchestrator"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    containers {
      image = "us-docker.pkg.dev/${var.project_id}/repo/supervisor:latest"
    }
    # 8. & 9. Agent Identity (SPIFFE) & Gateway (Service Account limits)
    service_account = google_service_account.agent_identity.email
  }
}

resource "google_service_account" "agent_identity" {
  account_id   = "agent-identity-spiffe"
  display_name = "Agent Down-Scoped Identity"
}

# IAM Binding for Cloud Run to access BigQuery
resource "google_project_iam_member" "bq_access" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.agent_identity.email}"
}

# IAM Binding for Cloud Run to access GCS
resource "google_project_iam_member" "gcs_access" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.agent_identity.email}"
}

