# 06: Testing, Evaluation, and Compliance Runbook

## 1. Zero-Dependency Local Testing
Before deploying to Google Cloud, developers must validate the agent mesh and streaming UI locally.
* **Stream & Schema Compliance Sandbox:** Pytest fixtures will simulate the multi-agent trace event emitters. Tests must verify that the backend correctly formats and streams JSON-RPC 2.0 payloads over SSE without invoking upstream language models or incurring API costs.
* **Mocked Epistemic Memory:** Local unit tests will mock the Shared Memory Bank to ensure agents correctly read and synthesize causal chains.

## 2. Groundedness Evaluation Gates (LLM-as-a-Judge)
To enforce the mechanical grounding mandate (Spec 03), CI/CD pipelines will incorporate automated evaluator scripts.
* **Evaluation Criteria:** An independent evaluator model reviews the output of the Exposure & Risk Summary Agent against the provided mock documents and enrichment payloads.
* **Pass/Fail Threshold:** The CI gate fails the build if the evaluator detects *any* ungrounded assertions or hallucinations. The target metric is strictly 0% uncited claims.

## 3. Compliance and Audit Trail Validation
A dedicated test suite will simulate end-to-end quote lifecycles and verify the generation of the "Regulator-Ready Audit Pack."
* **Test Assertions:**
    * Every generated quote option must contain a valid `audit_id`.
    * The exported audit pack must include:
        * The original Document AI extraction map.
        * The Apigee enrichment payload.
        * The exact Symbolic Rules Engine version and the array of triggered `Rule_IDs`.
    * Rerunning the exact same inputs through the Symbolic Engine API must produce identical numerical outputs and traces (Deterministic Verification).

## 4. End-to-End User Acceptance Testing (UAT)
UAT will focus on the Explainable AI Workbench.
* Verify that out-of-bounds quotes are correctly routed to the Referral Queue.
* Verify that underwriters can click on a rating factor in the A2UI and successfully drill down into the cited evidence snippet.

