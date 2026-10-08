/**
 * SYSTEM PATTERN: DYNAMIC CLIENT COMPONENT FACTORY & SSE PARSER ENGINE
 * This engine establishes an asynchronous network event pipeline, captures multi-agent trace logs,
 * maps coordinator topologies, and dynamically builds user interfaces from standard JSON definitions.
 */

class MultiAgentDynamicUiEngine {
    constructor(streamApiUrl, chatTerminalId, topologyPanelId) {
        this.streamApiUrl = streamApiUrl;
        this.chatTerminalId = chatTerminalId;
        this.topologyPanelId = topologyPanelId;
    }

    /**
     * Initializes network event stream pipelines via the Reactive Stream Parser Pattern
     */
    establishOrchestrationStream(userIntentPrompt, sharedSessionId) {
        const queryUrl = `${this.streamApiUrl}?prompt=${encodeURIComponent(userIntentPrompt)}&session_id=${encodeURIComponent(sharedSessionId)}`;
        const clientEventStreamSource = new EventSource(queryUrl);

        clientEventStreamSource.onmessage = (streamEvent) => {
            try {
                const rpcDataFrame = JSON.parse(streamEvent.data);
                this.executeComponentFactoryRouting(rpcDataFrame);
            } catch (payloadError) {
                console.error("Malformed application stream payload encountered:", payloadError);
            }
        };

        clientEventStreamSource.onerror = (networkError) => {
            console.error("System EventSource execution pipeline hit an error. Closing connection pipeline.", networkError);
            clientEventStreamSource.close();
        };
    }

    /**
     * Maps incoming event payloads directly to internal Dynamic Component Factory builders
     */
    executeComponentFactoryRouting(rpcDataFrame) {
        const { method, params } = rpcDataFrame;
        
        switch(method) {
            case "onAgentThought":
                this.appendLifecycleTraceText(params.author, params.message, "internal-thought-bubble-token");
                break;
            case "onAgentDelegation":
                this.mutateTopologyVisualizationGraph(params.author, params.target, params.message);
                break;
            case "onToolCall":
                this.appendLifecycleTraceText(params.author, `Invoking Tool Access Node: [${params.tool}]`, "tool-invocation-bubble-token");
                break;
            case "onUiComponentDelivery":
                this.buildDeclarativeWidgetFromSchema(params.payload, this.chatTerminalId);
                break;
            default:
                console.warn(`System Alert: Unhandled schema engine message method target: ${method}`);
        }
    }

    appendLifecycleTraceText(agentNodeName, logicalMessage, displayCssClassToken) {
        const terminalContainerNode = document.getElementById(this.chatTerminalId);
        const logRowWrapperNode = document.createElement("div");
        logRowWrapperNode.className = `base-terminal-bubble-layout ${displayCssClassToken}`;
        logRowWrapperNode.innerHTML = `<strong>${agentNodeName}:</strong><span>${logicalMessage}</span>`;
        terminalContainerNode.appendChild(logRowWrapperNode);
        terminalContainerNode.scrollTop = terminalContainerNode.scrollHeight;
    }

    /**
     * Dynamic Topology Tracker Pattern mapping physical structural components on the fly
     */
    mutateTopologyVisualizationGraph(sourceAgentNode, targetedAgentNode, executionContextMessage) {
        const visualizerPanelNode = document.getElementById(this.topologyPanelId);
        visualizerPanelNode.innerHTML = `
            <div class="active-mesh-topology-card-component">
                <div class="mesh-vector-trajectory-path">
                    <span class="agent-node architectural-blueprint-source">${sourceAgentNode}</span>
                    <span class="vector-pulse-indicator"> ➔ Routing Sub-Task Execution Boundary Context ➔ </span>
                    <span class="agent-node architectural-blueprint-target">${targetedAgentNode}</span>
                </div>
                <p class="mesh-execution-context-log-subtext">${executionContextMessage}</p>
            </div>
        `;
    }

    /**
     * PATTERN: DYNAMIC COMPONENT FACTORY
     * Processes programmatic layout instructions directly into functional DOM layouts without app compilation loops
     */
    buildDeclarativeWidgetFromSchema(componentSchemaPayload, interfaceTargetContainerId) {
        const outputContainerNode = document.getElementById(interfaceTargetContainerId);
        const runtimeWidgetWrapperNode = document.createElement("div");
        runtimeWidgetWrapperNode.className = "runtime-compiled-widget-wrapper-container";

        if (componentSchemaPayload.type === "Tabs") {
            const architecturalTabsHeaderNavNode = document.createElement("div");
            architecturalTabsHeaderNavNode.className = "ui-tabs-navigation-header-bar-layout";
            
            componentSchemaPayload.components.forEach((nestedComponentItem, systemIndexCounter) => {
                const operationalTabSelectionButton = document.createElement("button");
                operationalTabSelectionButton.className = `tab-selection-toggle-control-token ${systemIndexCounter === 0 ? 'active' : ''}`;
                operationalTabSelectionButton.innerText = nestedComponentItem.title;
                architecturalTabsHeaderNavNode.appendChild(operationalTabSelectionButton);
            });
            
            runtimeWidgetWrapperNode.appendChild(architecturalTabsHeaderNavNode);
            // Deep iterative structural factory execution runs downstream across inner items...
        }
        
        outputContainerNode.appendChild(runtimeWidgetWrapperNode);
        outputContainerNode.scrollTop = outputContainerNode.scrollHeight;
    }
}

