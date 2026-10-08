# 02: Neuro-Symbolic Rating Engine

## 1. Architectural Mandate
To guarantee deterministic execution and regulatory compliance, the rating and scoring logic is completely isolated from the Large Language Model. The architecture employs a **Neuro-Symbolic pattern**:
- **Neural Layer (LLMs):** Natural language understanding, document extraction (Doc AI), intent routing, and explanation generation.
- **Symbolic Layer (Code):** Explicit, version-controlled rules engines that own every score, rate, and decision.

## 2. Strict Constraints
* **Zero-LLM Pricing:** No agent model may output a rate, premium, score, or bind/decline decision natively.
* **Deterministic Output:** Identical inputs + Identical rule version MUST yield identical outputs.
* **Auditable Traceability:** Every calculation must attach a specific `Rule_ID` and `Version_ID`.

## 3. Implementation Details
The Symbolic Rating Engine will be implemented as an isolated Cloud Run service that exposes a strict REST API.

### Input Schema
* `quote_id`: UUID
* `extracted_entities`: JSON object bound to Doc AI extraction outputs.
* `enrichment_data`: JSON object bound to verified Apigee API payloads.
* `rule_version`: String (e.g., "v1.4.2")

### Execution Flow
1. The **Supervisor Agent** collects inputs from the Intake and Enrichment agents.
2. It constructs a strictly typed JSON payload.
3. It invokes the **Symbolic Rating Engine** API.
4. The engine evaluates the payload against its versioned rule trees.
5. The engine returns a calculated output payload containing:
    * `base_premium`
    * `adjusted_premium`
    * `risk_score`
    * `decision` (STP, Referral, Decline)
    * `execution_trace`: An array of `Rule_IDs` triggered during calculation.

## 4. Explainable AI Translation
Once the Symbolic Engine returns its trace, the **Exposure & Risk Summary Agent** translates the raw rule triggers into human-readable explanations for the A2UI workbench, without altering the numbers. The translation maps `Rule_ID` to natural language justifications, surfacing the precise risk factors that drove the premium.

