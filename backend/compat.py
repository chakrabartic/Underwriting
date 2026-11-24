"""ADK & A2UI runtime compatibility stabilization and callback contracts.

Implements Specification 07 without mutating unrelated standard-library modules:
1. Aligns `a2a.types.DataPart` and `a2a.types.TextPart` if an older/drifted
   `a2a` package is installed in the Python environment.
2. Enforces the ADK keyword-argument `callback_context` invocation contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import inspect
import logging
import sys
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FallbackDataPart:
    """Fallback A2UI DataPart payload container when `a2a` is not installed."""

    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FallbackTextPart:
    """Fallback A2UI TextPart payload container when `a2a` is not installed."""

    text: str


@dataclass(frozen=True, slots=True)
class CallbackContext:
    """Immutable execution context passed to ADK lifecycle callbacks."""

    session_id: str
    quote_id: str
    agent_name: str
    stage: str
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentLifecycleCallback(Protocol):
    """Protocol requiring the exact `callback_context` keyword parameter (Spec 07)."""

    def __call__(self, *, callback_context: CallbackContext) -> None: ...


def validate_adk_callback_signature(callback: Any) -> None:
    """Verifies that a callback accepts keyword argument `callback_context`.

    Raises:
        TypeError: If `callback` is not callable or cannot receive `callback_context`
            as a keyword argument.
    """
    if not callable(callback):
        raise TypeError(
            f"Expected callable lifecycle callback, got {type(callback).__name__}"
        )
    sig = inspect.signature(callback)
    params = sig.parameters
    if "callback_context" in params:
        param = params["callback_context"]
        if param.kind == inspect.Parameter.POSITIONAL_ONLY:
            raise TypeError(
                "ADK callback parameter 'callback_context' must not be positional-only."
            )
        return
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return
    raise TypeError(
        f"Callback {getattr(callback, '__name__', repr(callback))} must accept "
        "keyword argument 'callback_context' per Specification 07."
    )


def stabilize_a2a_runtime() -> dict[str, Any]:
    """Aligns `a2a.types` exports if `a2a` is present in the runtime environment."""
    try:
        a2a_types = importlib.import_module("a2a.types")
    except ImportError:
        logger.debug("Optional package 'a2a' not installed; using built-in part types.")
        return {
            "a2a_installed": False,
            "patched": False,
            "data_part_cls": FallbackDataPart.__name__,
            "text_part_cls": FallbackTextPart.__name__,
        }

    patched = False
    if not hasattr(a2a_types, "DataPart") or not hasattr(a2a_types, "TextPart"):
        try:
            compat_mod = importlib.import_module("a2a.compat.v0_3.types")
            data_part = getattr(compat_mod, "DataPart", FallbackDataPart)
            text_part = getattr(compat_mod, "TextPart", FallbackTextPart)
        except ImportError:
            data_part = FallbackDataPart
            text_part = FallbackTextPart

        setattr(a2a_types, "DataPart", data_part)
        setattr(a2a_types, "TextPart", text_part)
        sys.modules["a2a.types"] = a2a_types
        patched = True
        logger.info("Stabilized a2a.types DataPart and TextPart definitions.")

    return {
        "a2a_installed": True,
        "patched": patched,
        "data_part_cls": getattr(a2a_types, "DataPart").__name__,
        "text_part_cls": getattr(a2a_types, "TextPart").__name__,
    }
