variable "project_id" {
  description = "Target GCP project ID hosting the Underwriting Agentic Workbench."
  type        = string
  default     = "chayan-genai-bb"

  validation {
    condition     = length(trimspace(var.project_id)) > 4
    error_message = "project_id must be a valid non-empty GCP project identifier."
  }
}

variable "region" {
  description = "Primary GCP region for regional compute, storage, and serverless workloads."
  type        = string
  default     = "us-central1"
}

variable "docai_location" {
  description = "Document AI multi-region processor location ('us' or 'eu')."
  type        = string
  default     = "us"
}

variable "environment" {
  description = "Deployment environment label ('dev', 'staging', 'prod')."
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "orchestrator_image" {
  description = "Container image URI for the Supervisor Orchestrator Cloud Run service."
  type        = string
  default     = ""
}

variable "rating_engine_image" {
  description = "Container image URI for the isolated Symbolic Rating Engine Cloud Run service."
  type        = string
  default     = ""
}

variable "envoy_gateway_image" {
  description = "Container image URI for the Envoy-based Agent Gateway proxy."
  type        = string
  default     = "envoyproxy/envoy:v1.31-latest"
}

variable "looker_oauth_client_id" {
  description = "OAuth client ID required for Looker Core semantic-layer provisioning."
  type        = string
  sensitive   = true
  default     = "placeholder-looker-client-id"
}

variable "looker_oauth_client_secret" {
  description = "OAuth client secret required for Looker Core semantic-layer provisioning."
  type        = string
  sensitive   = true
  default     = "placeholder-looker-client-secret"
}

variable "enable_deletion_protection" {
  description = "Enables deletion protection on stateful clusters, datasets, and tables."
  type        = bool
  default     = true
}

variable "force_destroy_buckets" {
  description = "Allows bucket destruction when non-empty (set false in production for audit retention)."
  type        = bool
  default     = false
}

variable "orchestrator_ingress" {
  description = "Cloud Run ingress policy for the Supervisor Orchestrator."
  type        = string
  default     = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
}
