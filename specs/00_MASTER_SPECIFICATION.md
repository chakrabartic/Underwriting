# 00: Master Specification — Explainable AI Underwriting Workbench

## 1. Executive Summary
This project delivers a **Production-Ready Agentic Solution** for insurance underwriting. Developed under Google's AI Black Belt methodology, it transforms the end-to-end quoting lifecycle from a manual, fragmented process into a streamlined, highly automated pipeline. This system acts as a trusted advisor, enriching data and holistically summarizing risk while eliminating duplicate manual entry. 

## 2. Core Tenets & Requirements
* **Production-Ready:** Built to scale on Google Cloud using the Agentic Stack.
* **Neuro-Symbolic Architecture:** All rating, scoring, and pricing are strictly deterministic and rule-based. The AI handles unstructured data extraction and natural language explanation but zero financial calculations.
* **Mechanical Grounding:** Zero tolerance for hallucinations. Every claim is strictly grounded against documents, rule IDs, or verified enrichment data.
* **Explainable AI Workbench:** A transparent, A2UI-powered frontend providing brokers and underwriters with factor-by-factor score justifications.
* **Workflow Automation:** Autonomous straight-through processing for low-risk quotes and a human-in-the-loop referral queue for out-of-bounds cases.

## 3. Sub-Specifications Directory
* **[01_SUBAGENT_ROSTER_AND_WORKFLOW.md](./01_SUBAGENT_ROSTER_AND_WORKFLOW.md)**: Agent topology, lifecycle, and delegation flows.
* **[02_NEURO_SYMBOLIC_RATING_ENGINE.md](./02_NEURO_SYMBOLIC_RATING_ENGINE.md)**: Deterministic, LLM-free scoring and pricing algorithms.
* **[03_MECHANICAL_GROUNDING_AND_HALLUCINATION_ELIMINATION.md](./03_MECHANICAL_GROUNDING_AND_HALLUCINATION_ELIMINATION.md)**: Traceability and strict evidence-binding protocols.
* **[04_GCP_SERVICES_AND_SECURITY_TOPOLOGY.md](./04_GCP_SERVICES_AND_SECURITY_TOPOLOGY.md)**: Infrastructure map utilizing Cloud Storage, Doc AI, BigQuery, Apigee, Looker, GKE, Cloud Run, and Agent Gateway/Identity.
* **[05_A2UI_EXPLAINABLE_WORKBENCH_AND_STREAMING.md](./05_A2UI_EXPLAINABLE_WORKBENCH_AND_STREAMING.md)**: Frontend architecture and real-time streaming state.
* **[06_TESTING_EVALUATION_AND_COMPLIANCE_RUNBOOK.md](./06_TESTING_EVALUATION_AND_COMPLIANCE_RUNBOOK.md)**: Audit trail generation and groundedness evaluation gates.
* **[07_ADK_A2UI_API_ALIGNMENT_AND_COMPATIBILITY_NOTE.md](./07_ADK_A2UI_API_ALIGNMENT_AND_COMPATIBILITY_NOTE.md)**: Framework stabilization and dependency management.

## 4. Definition of Done
- Documents uploaded to Cloud Storage automatically yield priced quote options.
- 100% of numerical outputs trace to a rule ID and cited input.
- A2UI displays factor-by-factor justifications with drill-down evidence.
- Quote lifecycle management is comprehensive (no orphaned quotes).
- Secure tool execution via Agent Gateway + SPIFFE identity down-scoping.
- Groundedness CI/CD gating enforces zero uncited claims.

