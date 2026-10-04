"""
RAG service interfaces: EmbeddingService turns text into vectors,
VectorStore stores/searches them. Kept separate from the LLM interface
since a deployment might use, say, Anthropic for generation but a local
embedding model for retrieval - these rotate independently.
"""
from abc import ABC, abstractmethod
from typing import List

from ai.models.rag import RAGChunk


class EmbeddingService(ABC):
    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        """Embed a single string."""

    @abstractmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed many strings at once (batched where the provider supports it)."""


class VectorStore(ABC):
    @abstractmethod
    def add_documents(self, chunks: List[RAGChunk], embeddings: List[List[float]]) -> None: ...

    @abstractmethod
    def search(self, query_embedding: List[float], top_k: int = 5) -> List[RAGChunk]: ...

    @abstractmethod
    def delete(self, document_id: str) -> None:
        """Remove every chunk belonging to a document."""

    @abstractmethod
    def update(self, chunk: RAGChunk, embedding: List[float]) -> None: ...
