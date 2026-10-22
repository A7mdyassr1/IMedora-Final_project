"""
Agent/tool result models - the common envelope every tool call and every
agent run returns, so the orchestrator (Phase AI-12) can reason about
success/failure uniformly instead of each agent inventing its own shape.
"""
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Intent(str, Enum):
    DEVICE_QUERY = "DEVICE_QUERY"
    MAINTENANCE_QUERY = "MAINTENANCE_QUERY"
    TICKET_QUERY = "TICKET_QUERY"
    RISK_QUERY = "RISK_QUERY"
    QA_QUERY = "QA_QUERY"
    INVENTORY_QUERY = "INVENTORY_QUERY"
    ANALYTICS_QUERY = "ANALYTICS_QUERY"
    REPORT_QUERY = "REPORT_QUERY"
    KNOWLEDGE_QUERY = "KNOWLEDGE_QUERY"
    DOCUMENT_SEARCH = "DOCUMENT_SEARCH"
    GENERAL_QUERY = "GENERAL_QUERY"


class ToolResult(BaseModel):
    tool_name: str
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class AgentResult(BaseModel):
    agent_name: str
    success: bool
    output: Optional[str] = None
    tool_results: List[ToolResult] = Field(default_factory=list)
    error: Optional[str] = None
