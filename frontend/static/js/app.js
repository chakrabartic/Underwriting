/**
 * Dynamic A2UI Client Component Factory, Citation Inspector, & SSE Stream Engine.
 *
 * Security & Reliability Guarantees:
 * - Zero `innerHTML` untrusted string interpolation (XSS-safe DOM construction).
 * - Deterministic `EventSource` lifecycle cleanup preventing infinite reconnect loops.
 * - Recursive declarative schema rendering (`Tabs`, `Card`, `Table`) with interactive
 *   factor-by-factor citation drill-downs and HITL referral resolution.
 */

class MultiAgentDynamicUiEngine {
    constructor(streamApiUrl, chatTerminalId, topologyPanelId, options = {}) {
        this.streamApiUrl = streamApiUrl;
        this.chatTerminalId = chatTerminalId;
        this.topologyPanelId = topologyPanelId;
        this.evidenceInspectorId = options.evidenceInspectorId || null;
        this.quoteQueueId = options.quoteQueueId || null;
        this.lifecycleCountersId = options.lifecycleCountersId || null;
        this.statusBadgeId = options.statusBadgeId || null;
        this.referralConsoleId = options.referralConsoleId || null;

        this.activeEventSource = null;
        this.activeSessionId = `sess-${Math.random().toString(36).slice(2, 10)}`;
        this.activeQuoteId = null;
        this.activeCitations = {};
    }

    bindWorkbenchControls() {
        const scenarioSelect = document.getElementById("scenario-select");
        const promptInput = document.getElementById("prompt-input");
        const runBtn = document.getElementById("run-btn");
        const refreshBtn = document.getElementById("refresh-quotes-btn");
        const approveBtn = document.getElementById("approve-bind-btn");
        const requestInfoBtn = document.getElementById("request-info-btn");
        const declineBtn = document.getElementById("decline-quote-btn");
        const exportAuditBtn = document.getElementById("export-audit-btn");

        if (scenarioSelect && promptInput) {
            scenarioSelect.addEventListener("change", () => {
                promptInput.value = scenarioSelect.value;
            });
        }

        if (runBtn && promptInput) {
            runBtn.addEventListener("click", () => {
                this.clearContainer(this.chatTerminalId);
                this.clearContainer(this.topologyPanelId);
                this.establishOrchestrationStream(promptInput.value, this.activeSessionId);
            });
        }

        if (refreshBtn) {
            refreshBtn.addEventListener("click", () => this.refreshQuoteLifecycle());
        }

        if (approveBtn) {
            approveBtn.addEventListener("click", () => this.submitUnderwriterDecision("APPROVE_BIND"));
        }
        if (requestInfoBtn) {
            requestInfoBtn.addEventListener("click", () => this.submitUnderwriterDecision("REQUEST_INFO"));
        }
        if (declineBtn) {
            declineBtn.addEventListener("click", () => this.submitUnderwriterDecision("DECLINE"));
        }
        if (exportAuditBtn) {
            exportAuditBtn.addEventListener("click", () => this.inspectAuditPack());
        }
    }

    closeActiveStream() {
        if (this.activeEventSource) {
            this.activeEventSource.close();
            this.activeEventSource = null;
        }
    }

    setStreamStatus(label, stateClass) {
        if (!this.statusBadgeId) {
            return;
        }
        const badge = document.getElementById(this.statusBadgeId);
        if (badge) {
            badge.textContent = label;
            badge.className = `status-badge ${stateClass}`;
        }
    }

    clearContainer(containerId) {
        const node = containerId ? document.getElementById(containerId) : null;
        if (node) {
            node.replaceChildren();
        }
    }

    establishOrchestrationStream(userIntentPrompt, sharedSessionId) {
        this.closeActiveStream();
        this.setStreamStatus("Streaming...", "streaming");

        const queryUrl = (
            `${this.streamApiUrl}?prompt=${encodeURIComponent(userIntentPrompt)}` +
            `&session_id=${encodeURIComponent(sharedSessionId)}`
        );
        const eventSource = new EventSource(queryUrl);
        this.activeEventSource = eventSource;

        eventSource.onmessage = (streamEvent) => {
            try {
                const rpcDataFrame = JSON.parse(streamEvent.data);
                this.executeComponentFactoryRouting(rpcDataFrame);
            } catch (payloadError) {
                console.error("Malformed SSE JSON-RPC frame:", payloadError);
            }
        };

        eventSource.onerror = () => {
            this.closeActiveStream();
            this.setStreamStatus("Idle", "idle");
        };
    }

    executeComponentFactoryRouting(rpcDataFrame) {
        const { method, params } = rpcDataFrame;
        if (!params) {
            return;
        }

        switch (method) {
            case "onAgentThought":
                this.appendLifecycleTraceText(
                    params.author,
                    params.message,
                    "internal-thought-bubble-token"
                );
                break;
            case "onAgentDelegation":
                this.mutateTopologyVisualizationGraph(
                    params.author,
                    params.target,
                    params.message
                );
                break;
            case "onToolCall":
                this.appendLifecycleTraceText(
                    params.author,
                    `Authorized Tool via SPIFFE Gateway: [${params.tool}]`,
                    "tool-invocation-bubble-token"
                );
                break;
            case "onUiComponentDelivery":
                this.activeQuoteId = params.quote_id || null;
                this.activeCitations = params.citations || {};
                this.buildDeclarativeWidgetFromSchema(params.payload, this.chatTerminalId);
                this.configureReferralConsole(params.quote_id, params.lifecycle_state);
                break;
            case "onWorkflowComplete":
                this.closeActiveStream();
                this.setStreamStatus(`Completed (${params.lifecycle_state})`, "completed");
                this.refreshQuoteLifecycle();
                break;
            case "onWorkflowError":
                this.closeActiveStream();
                this.setStreamStatus("Quarantined Error", "error");
                this.appendLifecycleTraceText(
                    params.author || "SupervisorAgentCore",
                    `[${params.error_type}] ${params.message}`,
                    "error-bubble-token"
                );
                this.refreshQuoteLifecycle();
                break;
            default:
                console.warn(`Unhandled JSON-RPC method: ${method}`);
        }
    }

    appendLifecycleTraceText(agentNodeName, logicalMessage, displayCssClassToken) {
        const container = document.getElementById(this.chatTerminalId);
        if (!container) {
            return;
        }
        const bubble = document.createElement("div");
        bubble.className = `base-terminal-bubble-layout ${displayCssClassToken}`;

        const authorTag = document.createElement("strong");
        authorTag.textContent = `${agentNodeName}:`;

        const messageSpan = document.createElement("span");
        messageSpan.textContent = logicalMessage;

        bubble.appendChild(authorTag);
        bubble.appendChild(messageSpan);
        container.appendChild(bubble);
        container.scrollTop = container.scrollHeight;
    }

    mutateTopologyVisualizationGraph(sourceAgentNode, targetedAgentNode, executionContextMessage) {
        const panel = document.getElementById(this.topologyPanelId);
        if (!panel) {
            return;
        }
        const card = document.createElement("div");
        card.className = "active-mesh-topology-card-component";

        const pathRow = document.createElement("div");
        pathRow.className = "mesh-vector-trajectory-path";

        const sourceSpan = document.createElement("span");
        sourceSpan.className = "agent-node architectural-blueprint-source";
        sourceSpan.textContent = sourceAgentNode;

        const arrowSpan = document.createElement("span");
        arrowSpan.className = "vector-pulse-indicator";
        arrowSpan.textContent = "->";

        const targetSpan = document.createElement("span");
        targetSpan.className = "agent-node architectural-blueprint-target";
        targetSpan.textContent = targetedAgentNode;

        pathRow.appendChild(sourceSpan);
        pathRow.appendChild(arrowSpan);
        pathRow.appendChild(targetSpan);

        const subtext = document.createElement("p");
        subtext.className = "mesh-execution-context-log-subtext";
        subtext.textContent = executionContextMessage;

        card.appendChild(pathRow);
        card.appendChild(subtext);
        panel.appendChild(card);
        panel.scrollTop = panel.scrollHeight;
    }

    buildDeclarativeWidgetFromSchema(componentSchemaPayload, interfaceTargetContainerId) {
        const outputContainer = document.getElementById(interfaceTargetContainerId);
        if (!outputContainer || !componentSchemaPayload) {
            return;
        }
        const widgetNode = this.renderSchemaNode(componentSchemaPayload);
        outputContainer.appendChild(widgetNode);
        outputContainer.scrollTop = outputContainer.scrollHeight;
    }

    renderSchemaNode(schema) {
        const wrapper = document.createElement("div");
        wrapper.className = "runtime-compiled-widget-wrapper-container";

        if (schema.type === "Tabs" && Array.isArray(schema.components)) {
            if (schema.quote_id) {
                const summaryBanner = document.createElement("div");
                summaryBanner.className = "quote-summary-banner";
                summaryBanner.textContent = (
                    `Quote ${schema.quote_id} | State: ${schema.lifecycle_state || "ACTIVE"} | ` +
                    `Decision: ${schema.decision || "N/A"} | Risk Score: ${schema.risk_score ?? "N/A"}`
                );
                wrapper.appendChild(summaryBanner);
            }

            const tabHeader = document.createElement("div");
            tabHeader.className = "ui-tabs-navigation-header-bar-layout";

            const tabBodyContainer = document.createElement("div");
            tabBodyContainer.className = "ui-tabs-content-body";

            const panes = [];
            const buttons = [];

            schema.components.forEach((item, index) => {
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = `tab-selection-toggle-control-token ${index === 0 ? "active" : ""}`;
                btn.textContent = item.title || `Tab ${index + 1}`;

                const pane = document.createElement("div");
                pane.className = `ui-tab-pane ${index === 0 ? "active" : "hidden"}`;
                pane.appendChild(this.renderLeafComponent(item));

                btn.addEventListener("click", () => {
                    buttons.forEach((b, idx) => {
                        b.classList.toggle("active", idx === index);
                    });
                    panes.forEach((p, idx) => {
                        p.classList.toggle("active", idx === index);
                        p.classList.toggle("hidden", idx !== index);
                    });
                });

                buttons.push(btn);
                panes.push(pane);
                tabHeader.appendChild(btn);
                tabBodyContainer.appendChild(pane);
            });

            wrapper.appendChild(tabHeader);
            wrapper.appendChild(tabBodyContainer);
            return wrapper;
        }

        wrapper.appendChild(this.renderLeafComponent(schema));
        return wrapper;
    }

    renderLeafComponent(component) {
        const box = document.createElement("div");
        box.className = "a2ui-leaf-component";

        if (component.type === "Card") {
            if (Array.isArray(component.assertions) && component.assertions.length > 0) {
                const list = document.createElement("ul");
                list.className = "grounded-assertion-list";
                component.assertions.forEach((assertion) => {
                    const li = document.createElement("li");
                    const textSpan = document.createElement("span");
                    textSpan.textContent = `${assertion.claim_text} `;
                    li.appendChild(textSpan);

                    (assertion.citation_uris || []).forEach((uri) => {
                        li.appendChild(this.createCitationBadge(uri));
                    });
                    list.appendChild(li);
                });
                box.appendChild(list);
            } else {
                const p = document.createElement("p");
                p.className = "a2ui-card-text";
                p.textContent = component.content || "";
                box.appendChild(p);
            }
            return box;
        }

        if (component.type === "Table") {
            const table = document.createElement("table");
            table.className = "a2ui-data-table";

            if (Array.isArray(component.headers)) {
                const thead = document.createElement("thead");
                const tr = document.createElement("tr");
                component.headers.forEach((headerText) => {
                    const th = document.createElement("th");
                    th.textContent = headerText;
                    tr.appendChild(th);
                });
                thead.appendChild(tr);
                table.appendChild(thead);
            }

            const tbody = document.createElement("tbody");
            const rows = Array.isArray(component.rows) ? component.rows : [];
            if (rows.length === 0) {
                const emptyRow = document.createElement("tr");
                const td = document.createElement("td");
                td.colSpan = (component.headers || []).length || 1;
                td.className = "empty-table-cell";
                td.textContent = "No applicable entries for this submission.";
                emptyRow.appendChild(td);
                tbody.appendChild(emptyRow);
            } else {
                rows.forEach((rowCells) => {
                    const tr = document.createElement("tr");
                    rowCells.forEach((cellVal) => {
                        const td = document.createElement("td");
                        const strVal = String(cellVal ?? "");
                        if (
                            strVal.startsWith("docai://") ||
                            strVal.startsWith("apigee://") ||
                            strVal.startsWith("rule://")
                        ) {
                            td.appendChild(this.createCitationBadge(strVal));
                        } else {
                            td.textContent = strVal;
                        }
                        tr.appendChild(td);
                    });
                    tbody.appendChild(tr);
                });
            }
            table.appendChild(tbody);
            box.appendChild(table);
            return box;
        }

        const fallback = document.createElement("pre");
        fallback.textContent = JSON.stringify(component, null, 2);
        box.appendChild(fallback);
        return box;
    }

    createCitationBadge(citationUri) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "citation-pill-btn";
        const shortLabel = citationUri.split("/").slice(-1)[0] || citationUri;
        btn.textContent = shortLabel;
        btn.title = citationUri;
        btn.addEventListener("click", () => this.showEvidenceDrillDown(citationUri));
        return btn;
    }

    showEvidenceDrillDown(citationUri) {
        if (!this.evidenceInspectorId) {
            return;
        }
        const inspector = document.getElementById(this.evidenceInspectorId);
        if (!inspector) {
            return;
        }
        inspector.replaceChildren();

        const record = this.activeCitations[citationUri];
        const card = document.createElement("div");
        card.className = "evidence-detail-card";

        const title = document.createElement("h3");
        title.textContent = record ? `Source: ${record.source_type}` : "Citation Reference";
        card.appendChild(title);

        const uriLine = document.createElement("code");
        uriLine.className = "evidence-uri";
        uriLine.textContent = citationUri;
        card.appendChild(uriLine);

        const metaPre = document.createElement("pre");
        metaPre.className = "evidence-json";
        metaPre.textContent = JSON.stringify(
            record || { citation_uri: citationUri, status: "URI registered in session" },
            null,
            2
        );
        card.appendChild(metaPre);
        inspector.appendChild(card);
    }

    configureReferralConsole(quoteId, lifecycleState) {
        if (!this.referralConsoleId) {
            return;
        }
        const consoleEl = document.getElementById(this.referralConsoleId);
        const labelEl = document.getElementById("referral-quote-label");
        if (!consoleEl) {
            return;
        }
        if (!quoteId) {
            consoleEl.classList.add("hidden");
            return;
        }
        consoleEl.classList.remove("hidden");
        if (labelEl) {
            labelEl.textContent = `Quote ${quoteId} (${lifecycleState || "ACTIVE"})`;
        }
        const actionable = lifecycleState === "REFERRAL_QUEUE" || lifecycleState === "QUOTED_STP" || lifecycleState === "INFO_REQUESTED";
        ["approve-bind-btn", "request-info-btn", "decline-quote-btn"].forEach((id) => {
            const btn = document.getElementById(id);
            if (btn) {
                btn.disabled = !actionable;
            }
        });
    }

    async submitUnderwriterDecision(action) {
        if (!this.activeQuoteId) {
            return;
        }
        const rationaleInput = document.getElementById("underwriter-rationale-input");
        const rationale = (rationaleInput && rationaleInput.value.trim()) || `Underwriter selected ${action}`;
        try {
            const resp = await fetch(`/api/quotes/${encodeURIComponent(this.activeQuoteId)}/decision`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    action,
                    underwriter_id: "uw-senior-01",
                    rationale,
                }),
            });
            const data = await resp.json();
            if (!resp.ok) {
                this.appendLifecycleTraceText("ReferralConsole", data.error || "Decision failed", "error-bubble-token");
                return;
            }
            this.appendLifecycleTraceText(
                "ReferralConsole",
                `Quote ${data.quote_id} transitioned to ${data.state} (${action}). Audit pack re-sealed.`,
                "internal-thought-bubble-token"
            );
            this.configureReferralConsole(data.quote_id, data.state);
            await this.refreshQuoteLifecycle();
        } catch (err) {
            console.error("Failed submitting HITL decision:", err);
        }
    }

    async inspectAuditPack() {
        if (!this.activeQuoteId || !this.evidenceInspectorId) {
            return;
        }
        try {
            const resp = await fetch(`/api/quotes/${encodeURIComponent(this.activeQuoteId)}/audit`);
            const auditPayload = await resp.json();
            const inspector = document.getElementById(this.evidenceInspectorId);
            if (!inspector) {
                return;
            }
            inspector.replaceChildren();
            const card = document.createElement("div");
            card.className = "evidence-detail-card";
            const heading = document.createElement("h3");
            heading.textContent = `Regulator-Ready Audit Pack (${auditPayload.audit_id || "Export"})`;
            const pre = document.createElement("pre");
            pre.className = "evidence-json";
            pre.textContent = JSON.stringify(auditPayload, null, 2);
            card.appendChild(heading);
            card.appendChild(pre);
            inspector.appendChild(card);
        } catch (err) {
            console.error("Failed fetching audit pack:", err);
        }
    }

    async refreshQuoteLifecycle() {
        try {
            const resp = await fetch("/api/quotes");
            if (!resp.ok) {
                return;
            }
            const payload = await resp.json();
            this.renderLifecycleCounters(payload.counts_by_state || {});
            this.renderQuoteQueue(payload.quotes || []);
        } catch (err) {
            console.error("Failed refreshing quote lifecycle:", err);
        }
    }

    renderLifecycleCounters(counts) {
        if (!this.lifecycleCountersId) {
            return;
        }
        const root = document.getElementById(this.lifecycleCountersId);
        if (!root) {
            return;
        }
        root.querySelectorAll(".counter-chip").forEach((chip) => {
            const stateKey = chip.getAttribute("data-state");
            const strong = chip.querySelector("strong");
            if (strong && stateKey) {
                strong.textContent = String(counts[stateKey] ?? 0);
            }
        });
    }

    renderQuoteQueue(quotes) {
        if (!this.quoteQueueId) {
            return;
        }
        const container = document.getElementById(this.quoteQueueId);
        if (!container) {
            return;
        }
        container.replaceChildren();
        if (quotes.length === 0) {
            const p = document.createElement("p");
            p.className = "empty-hint";
            p.textContent = "No submissions processed yet.";
            container.appendChild(p);
            return;
        }

        quotes.forEach((q) => {
            const item = document.createElement("button");
            item.type = "button";
            item.className = "quote-queue-item";

            const topRow = document.createElement("div");
            topRow.className = "quote-queue-row";
            const idStrong = document.createElement("strong");
            idStrong.textContent = q.quote_id;
            const stateSpan = document.createElement("span");
            stateSpan.className = `state-pill state-${String(q.state).toLowerCase()}`;
            stateSpan.textContent = q.state;
            topRow.appendChild(idStrong);
            topRow.appendChild(stateSpan);

            const subRow = document.createElement("div");
            subRow.className = "quote-queue-sub";
            const premText = q.adjusted_premium != null ? `$${Number(q.adjusted_premium).toLocaleString()}` : "N/A";
            subRow.textContent = `${q.business_name} • ${premText}`;

            item.appendChild(topRow);
            item.appendChild(subRow);
            item.addEventListener("click", () => this.loadDossierFromMemory(q.quote_id));
            container.appendChild(item);
        });
    }

    async loadDossierFromMemory(quoteId) {
        try {
            const resp = await fetch(`/api/quotes/${encodeURIComponent(quoteId)}`);
            if (!resp.ok) {
                return;
            }
            const dossier = await resp.json();
            this.activeQuoteId = dossier.quote_id;
            this.activeCitations = dossier.citations || {};
            this.configureReferralConsole(dossier.quote_id, dossier.state);

            if (this.evidenceInspectorId) {
                const inspector = document.getElementById(this.evidenceInspectorId);
                if (inspector) {
                    inspector.replaceChildren();
                    const card = document.createElement("div");
                    card.className = "evidence-detail-card";
                    const title = document.createElement("h3");
                    title.textContent = `Epistemic Memory Dossier: ${dossier.quote_id}`;
                    const pre = document.createElement("pre");
                    pre.className = "evidence-json";
                    pre.textContent = JSON.stringify(
                        {
                            state: dossier.state,
                            business_name: dossier.business_name,
                            adjusted_premium: dossier.adjusted_premium,
                            risk_score: dossier.risk_score,
                            state_history: dossier.state_history,
                            memory_notes_count: (dossier.memory_notes || []).length,
                        },
                        null,
                        2
                    );
                    card.appendChild(title);
                    card.appendChild(pre);
                    inspector.appendChild(card);
                }
            }
        } catch (err) {
            console.error("Failed loading quote dossier:", err);
        }
    }
}
