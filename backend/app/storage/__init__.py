"""File storage for attachments (B5, Decision 5): one small interface, chosen by STORAGE_BACKEND."""
from functools import lru_cache

from app.core.config import get_settings
from app.storage.base import FileNotAvailable, Storage
from app.storage.local import LocalDiskStorage

__all__ = ["FileNotAvailable", "LocalDiskStorage", "Storage", "get_storage"]


@lru_cache
def get_storage() -> Storage:
    settings = get_settings()
    if settings.storage_backend == "local":
        return LocalDiskStorage(settings.storage_dir)
    raise RuntimeError(f"Unsupported STORAGE_BACKEND {settings.storage_backend!r}")  # pragma: no cover - Literal
