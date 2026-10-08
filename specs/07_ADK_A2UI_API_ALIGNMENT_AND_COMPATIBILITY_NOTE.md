# 07: ADK & A2UI API Alignment and Compatibility Note

## 1. System Drift and Framework Stabilization
As noted in the AI Black Belt methodology, enterprise multi-agent frameworks often experience rapid iteration, leading to discrepancies between backend agent execution models and frontend UI type definitions. 

## 2. Runtime Environment Stabilization Pattern
To ensure type safety and stable execution without modifying frozen dependencies or waiting for upstream patches, this architecture employs a **Monkeypatching Stabilization Proxy** at the application bootstrap layer.

### Example Mitigation (A2UI Site-Package Mismatch)
If the `a2ui-agent-sdk` expects explicit `DataPart` and `TextPart` models, but the core ADK exports Protobuf classes, the backend orchestrator (`app.py`) will intercept the import and align the structural dependencies dynamically:

```python
import sys
import logging

try:
    import a2a.types
    from a2a.compat.v0_3.types import DataPart, TextPart
    a2a.types.DataPart = DataPart
    a2a.types.TextPart = TextPart
    sys.modules['a2a.types'] = a2a.types
    logging.info("A2A type definitions stabilized.")
except ImportError:
    logging.warning("Import drift detected. Stabilization may be required.")
```

## 3. Callback Parameter Binding
The ADK engine invokes user-defined callbacks by strictly mapping keyword arguments. Positional parameters will result in `TypeErrors`.
* **Standard:** All agent callbacks MUST use the exact keyword parameter name `callback_context`.

```python
# Correct Pattern
def before_agent_callback(callback_context):
    pass
```

## 4. Memory Bank Key Binding
When deploying agents that rely on the Shared Epistemic Memory Layer, customer entity keys (e.g., `quote_id`, `submission_id`) must be strictly synchronized with the overarching session scope before agent initialization to prevent context fragmentation.

