"""
Tool registry - the single place agents look tools up.

`build_registry(provider)` binds every tool to a DataProvider and
returns {tool_name: ToolSpec}. Agents (Phases AI-8..12) call
`registry.call("get_device", device_id="dev-001")` and always get a
ToolResult back; they never import individual tool modules and never see
the provider. When a real LLM is wired in (Phase AI-7), `describe()`
gives it the tool names + descriptions to choose from.
"""
import functools
import inspect
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from ai.models.agent import ToolResult
from ai.services.data.base import DataProvider
from ai.tools.analytics_tools.analytics_tools import TOOLS as ANALYTICS_TOOLS
from ai.tools.device_tools.device_tools import TOOLS as DEVICE_TOOLS
from ai.tools.inventory_tools.inventory_tools import TOOLS as INVENTORY_TOOLS
from ai.tools.maintenance_tools.maintenance_tools import TOOLS as MAINTENANCE_TOOLS
from ai.tools.qa_tools.qa_tools import TOOLS as QA_TOOLS
from ai.tools.risk_tools.risk_tools import TOOLS as RISK_TOOLS
from ai.tools.ticket_tools.ticket_tools import TOOLS as TICKET_TOOLS

ALL_TOOLS = [*DEVICE_TOOLS, *MAINTENANCE_TOOLS, *TICKET_TOOLS, *RISK_TOOLS, *QA_TOOLS, *INVENTORY_TOOLS, *ANALYTICS_TOOLS]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    category: str
    description: str
    parameters: List[str]
    func: Callable[..., ToolResult]


class ToolRegistry:
    def __init__(self, specs: Dict[str, ToolSpec]):
        self._specs = specs

    def names(self) -> List[str]:
        return sorted(self._specs)

    def get(self, name: str) -> ToolSpec:
        return self._specs[name]

    def has(self, name: str) -> bool:
        return name in self._specs

    def by_category(self, category: str) -> List[ToolSpec]:
        return [s for s in self._specs.values() if s.category == category]

    def call(self, name: str, **kwargs: Any) -> ToolResult:
        """Call a tool by name. An unknown name is a ToolResult failure, not an exception."""
        if name not in self._specs:
            return ToolResult(tool_name=name, success=False, error=f"Unknown tool: {name}")
        return self._specs[name].func(**kwargs)

    def describe(self) -> List[Dict[str, Any]]:
        return [
            {"name": s.name, "category": s.category, "description": s.description, "parameters": s.parameters}
            for s in sorted(self._specs.values(), key=lambda s: s.name)
        ]


def build_registry(provider: DataProvider) -> ToolRegistry:
    specs: Dict[str, ToolSpec] = {}
    for fn in ALL_TOOLS:
        # `fn.__wrapped__` is the undecorated function - used to read the real signature/docstring.
        raw = fn.__wrapped__  # type: ignore[attr-defined]
        params = [p for p in inspect.signature(raw).parameters if p != "provider"]
        doc = (inspect.getdoc(raw) or "").strip().splitlines()[0] if inspect.getdoc(raw) else ""
        spec = ToolSpec(
            name=fn.tool_name,  # type: ignore[attr-defined]
            category=fn.category,  # type: ignore[attr-defined]
            description=doc,
            parameters=params,
            func=functools.partial(fn, provider),
        )
        if spec.name in specs:
            raise ValueError(f"Duplicate tool name: {spec.name}")
        specs[spec.name] = spec
    return ToolRegistry(specs)
