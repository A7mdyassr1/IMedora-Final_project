"""
LLMService - abstraction over whatever LLM provider is configured
(Anthropic, OpenAI, or a deterministic mock for tests/CLI use before any
real API key exists). Agents depend on this interface only.
"""
from abc import ABC, abstractmethod
from typing import Iterator, Optional, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMService(ABC):
    @abstractmethod
    def generate(self, prompt: str, system: Optional[str] = None, **kwargs) -> str:
        """Plain-text completion."""

    @abstractmethod
    def generate_structured(self, prompt: str, schema: Type[T], system: Optional[str] = None, **kwargs) -> T:
        """Completion validated and parsed into the given Pydantic model."""

    @abstractmethod
    def stream(self, prompt: str, system: Optional[str] = None, **kwargs) -> Iterator[str]:
        """Yields text chunks as they're generated."""
