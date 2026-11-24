output "submissions_bucket_name" {
  description = "Cloud Storage bucket receiving incoming policy submissions."
  value       = google_storage_bucket.submissions.name
}

output "quotes_bucket_name" {
  description = "Cloud Storage bucket storing outbound quote proposals and decline notices."
  value       = google_storage_bucket.quotes.name
}

output "docai_processor_id" {
  description = "Document AI processor resource ID enforcing coordinate grounding."
  value       = google_document_ai_processor.intake_extractor.id
}

output "bigquery_dataset_id" {
  description = "BigQuery dataset tracking quote lifecycles and regulatory audit packs."
  value       = google_bigquery_dataset.quote_lifecycle.dataset_id
}

output "orchestrator_service_uri" {
  description = "HTTPS endpoint of the Supervisor Orchestrator Cloud Run service."
  value       = google_cloud_run_v2_service.orchestrator.uri
}

output "symbolic_rating_service_uri" {
  description = "Internal HTTPS endpoint of the isolated Symbolic Rating Engine."
  value       = google_cloud_run_v2_service.symbolic_rating_engine.uri
}

output "agent_gateway_service_uri" {
  description = "Internal HTTPS endpoint of the Envoy Agent Gateway proxy."
  value       = google_cloud_run_v2_service.agent_gateway.uri
}

output "spiffe_workload_identity_pool" {
  description = "Workload Identity Pool name backing SPIFFE agent token federation."
  value       = google_iam_workload_identity_pool.spiffe_agent_pool.name
}
