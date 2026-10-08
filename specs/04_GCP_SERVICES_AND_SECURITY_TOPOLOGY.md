# 04: GCP Services and Security Topology

## 1. Cloud Architecture Overview
The solution leverages Google Cloud Platform's serverless and managed services to deliver a scalable, enterprise-grade architecture. All services will be provisioned using Terraform to ensure reproducible infrastructure.

## 2. Component Mapping

| Service | Architecture Role |
| :--- | :--- |
| **Cloud Storage** | Secure storage for incoming policy documents, external attachments, and generated quote PDFs. |
| **Document AI** | Ingests unstructured data (PDFs) to extract entities, reducing hallucination by providing exact coordinate citations for grounding. |
| **BigQuery** | Centralized data warehouse for storing unstructured document metadata, extracted entities, and providing the corpus for embeddings/analytics. |
| **Apigee** | API Gateway managing orchestration and rate-limiting for external data enrichment integrations (e.g., property data, loss history). |
| **Looker** | Semantic layer and BI presentation tool for underwriter performance dashboards and portfolio risk analytics. |
| **Agent Gateway** | Envoy-based egress/ingress proxying securing tool-level authorization across the multi-agent mesh. |
| **Agent Identity** | SPIFFE-based identity provider ensuring down-scoped, ephemeral tokens for agents executing secure tool calls. |
| **Cloud Run** | Serverless execution environment hosting the stateless Agent Functions, Supervisor Orchestrator, and the Symbolic Rating Engine API. |
| **GKE (Kubernetes Engine)** | Hosts stateful container deployments, vector databases, and long-running background tasks alongside Cloud Run. |

## 3. Security and Authorization Flow
1. **Request Origin:** User interacts with A2UI, sending a request to the backend.
2. **Agent Identity:** The Supervisor Agent assumes a SPIFFE-based workload identity.
3. **Tool Invocation:** Before invoking a tool (e.g., calling BigQuery or an Apigee endpoint), the agent requests a down-scoped token from Agent Identity.
4. **Agent Gateway Proxy:** The request is routed through the Envoy-based Agent Gateway, which validates the down-scoped token and authorizes the specific tool execution.
5. **Data Locality:** All processing remains within the configured Google Cloud region, ensuring compliance with data sovereignty regulations.

## 4. Terraform Provisioning
The entire topology, including IAM roles, service accounts, buckets, and Cloud Run/GKE clusters, will be codified in HCL. This ensures the environment can be spun up, audited, and destroyed automatically.

