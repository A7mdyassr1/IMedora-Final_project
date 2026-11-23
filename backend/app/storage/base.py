"""Storage interface (Decision 5): save / open / delete by an opaque, server-generated key.

Keys are stored in attachments.file_url as "<backend>:<key>" - an internal reference, never a
public URL. Files are only ever served by the API after an authorization check.
"""
from typing import Protocol


class FileNotAvailable(Exception):
    """The key is unknown, malformed, or its file is missing."""


class Storage(Protocol):
    scheme: str  # prefix of the stored reference, e.g. "local"

    def save(self, content: bytes, extension: str) -> str:
        """Store new content under a fresh random key; returns the key."""

    def open(self, key: str) -> bytes:
        """The content of a key (FileNotAvailable when it does not exist)."""

    def delete(self, key: str) -> None:
        """Remove a key's file; a missing file is not an error."""
