# 05: A2UI Explainable Workbench and Streaming

## 1. The Explainable AI Workbench
The user interface, built on the A2UI framework, is a "glassmorphic" web application that serves as the underwriter's primary command center. Its primary design goal is **explainability**.

## 2. Key Interface Components
* **Quote Lifecycle Dashboard:** A kanban-style or list view showing all quotes grouped by status (Intake, Quoted-STP, Referral Queue, Bound, Declined). No quote can become "orphaned."
* **Factor-by-Factor Score Justification:** For any given quote, the UI dynamically renders a breakdown of the risk score.
    * Each contributing factor (e.g., "Roof Age > 20 Years") displays its mathematical impact on the premium.
    * **Evidence Drill-Down:** Clicking a factor reveals the exact snippet from the source document (via Doc AI) or the external data payload (via Apigee) that triggered the rule.
* **Human-in-the-Loop Referral Console:** For out-of-bounds or mediocre-risk cases, underwriters receive a synthesized briefing. The UI allows them to override specific rules or request additional information.

## 3. Real-Time Streaming Architecture
The UI is strictly decoupled from the multi-agent execution frames.
* **Reactive Controller Pattern:** The backend orchestrator (Supervisor) yields JSON-RPC formatted trace logs detailing state transitions.
* **Server-Sent Events (SSE):** These trace logs are streamed directly to the A2UI client over an SSE connection (`text/event-stream`).
* **Dynamic Component Assembly:** The A2UI client intercepts stream events (`onUiComponentDelivery`) and dynamically constructs the interface (tabs, tables, cards) based on JSON schemas sent by the backend. This prevents blocking UI threads and provides a real-time, transparent view of the agent mesh at work.

## 4. Integration with Shared Epistemic Memory
When an underwriter opens a quote in the referral queue, the UI retrieves the current state from the Shared Epistemic Memory Layer. The underwriter does not need to ask the agent "what is the status?"—the UI is already populated with the full causal chain of the submission.

