"""
Shared infrastructure for every AI tool.

A tool is a plain function `tool(provider, **args) -> ToolResult`. The
@tool decorator guarantees three things for all of them:

1. They always return a ToolResult - never raise to the caller. A real
   fault (e.g. the backend being down, once it exists) becomes
   `success=False` with an error message the agent can report honestly.
2. "No data" is NOT a failure. A missing device is `success=True` with
   `data["found"] == False`, so an agent can say "that device doesn't
   exist" instead of mistaking it for a crash or - worse - inventing an
   answer. This is what enforces the brief's "do not allow the LLM to
   fabricate database results".
3. Every call is logged (tool name, duration, outcome) - never the
   arguments' secrets, because tools take ids/filters, not credentials.
"""
import functools
import logging
import time
from datetime import date
from typing import Any, Callable, Dict, Iterable, Optional, Union

from pydantic import BaseModel

from ai.models.agent import ToolResult

logger = logging.getLogger("imedora.ai.tools")


def to_date(value: Union[None, str, date]) -> Optional[date]:
    """Accept either a date or an ISO string (LLM tool-calls pass strings)."""
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _dump(obj: Any) -> Any:
    return obj.model_dump(mode="json") if isinstance(obj, BaseModel) else obj


def single(item: Optional[BaseModel], what: str = "record") -> Dict[str, Any]:
    """Shape for 'one thing or nothing'."""
    if item is None:
        return {"found": False, "item": None, "message": f"No {what} found."}
    return {"found": True, "item": _dump(item)}


def many(items: Iterable[BaseModel], what: str = "records") -> Dict[str, Any]:
    """Shape for 'a list' (possibly empty)."""
    dumped = [_dump(i) for i in items]
    return {"count": len(dumped), "items": dumped, "message": None if dumped else f"No {what} found."}


def stats(values: Dict[str, Any], **filters: Any) -> Dict[str, Any]:
    """Shape for statistics dicts - always echoes the filters that were applied."""
    return {"statistics": values, "filters_applied": {k: v for k, v in filters.items() if v is not None}}


def tool(category: str) -> Callable:
    """Decorator turning `fn(provider, ...) -> dict` into a safe, logged tool."""

    def decorator(fn: Callable[..., Dict[str, Any]]) -> Callable[..., ToolResult]:
        name = fn.__name__

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> ToolResult:
            started = time.perf_counter()
            try:
                data = fn(*args, **kwargs)
                result = ToolResult(tool_name=name, success=True, data=data)
            except Exception as exc:  # noqa: BLE001 - a tool must never raise to its caller
                result = ToolResult(tool_name=name, success=False, error=f"{type(exc).__name__}: {exc}")
            logger.info(
                "tool=%s category=%s success=%s duration_ms=%.2f",
                name, category, result.success, (time.perf_counter() - started) * 1000,
            )
            return result

        wrapper.is_tool = True  # type: ignore[attr-defined]
        wrapper.tool_name = name  # type: ignore[attr-defined]
        wrapper.category = category  # type: ignore[attr-defined]
        return wrapper

    return decorator
