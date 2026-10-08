# 01: Subagent Roster and Workflow

## 1. Multi-Agent Topology Overview
The underwriting lifecycle is managed by an orchestrated mesh of highly specialized agents (Google ADK). A Supervisor Agent intercepts the initial submission and routes contextual payloads across a decentralized mesh of specialized workers.

## 2. Agent Roster

### A. Intake & Clearance Agent
* **Role**: Ingests unstructured policy documents from Google Cloud Storage, extracts key entities using Document AI, and registers a new quote in the centralized Quote Lifecycle database.
* **Constraints**: Purely extractive. Grounding enforced via Doc AI coordinates.

### B. Appetite & Eligibility Agent
* **Role**: Evaluates the extracted entities against the carrier's codified appetite guide.
* **Constraints**: Outputs binary decisions (Eligible / Ineligible / Referral) bound strictly to documented appetite rule IDs.

### C. Data Enrichment Agent
* **Role**: Integrates with third-party apis (via Apigee) to pull external risk data (e.g., property characteristics, loss history).
* **Constraints**: Maps API payload structures into the shared epistemic memory layer.

### D. Exposure & Risk Summary Agent
* **Role**: Synthesizes structured data from intake and enrichment into a holistic, human-readable risk summary.
* **Constraints**: Subject to rigorous groundedness checks. Cannot state facts not present in prior agent outputs.

### E. Symbolic Rating & Scoring Engine (Non-LLM)
* **Role**: The deterministic rules layer. Calculates premiums, applies risk modifiers, and generates the final quote scores.
* **Constraints**: **ZERO LLM CALLS.** Version-controlled Python ruleset providing deterministic, auditable mathematical outputs.

### F. Quote & Document Generation Agent
* **Role**: Compiles multiple priced options and generates the final quote proposal documents.
* **Constraints**: Formats the output of the Symbolic Rating Engine without altering numerical values.

### G. Audit & Compliance Agent
* **Role**: Continuous background observer that builds a regulator-ready audit pack detailing every step, rule ID, and data source used in a decision.

## 3. Workflow Execution Path
1. **Submission**: Broker uploads a PDF to a Cloud Storage bucket.
2. **Clearance**: Intake Agent uses Doc AI to extract entities; BigQuery logs the event.
3. **Enrichment**: Data Enrichment Agent fetches external variables via Apigee.
4. **Analysis**: Exposure Agent synthesizes a summary.
5. **Rating**: The Symbolic Engine deterministically calculates the risk score and premiums.
6. **Decision**: Low-risk submissions are pushed to Straight-Through Processing (STP). Out-of-bounds submissions are routed to the Underwriter Referral Queue via the A2UI workbench.
7. **Quote**: Quote Agent generates multiple quoting tiers based on the deterministic scoring.

