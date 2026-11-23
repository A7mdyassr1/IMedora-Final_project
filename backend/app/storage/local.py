"""Local-disk storage (Decision 5: LocalDiskStorage now, S3-compatible later).

- Keys are generated here: "<2 hex>/<32 hex><.jpg|.png>" (random, sharded in 256 folders). Client
  file names never reach the file system, so there is no path traversal; keys read back from the
  database are validated against the same pattern and must resolve inside the root.
- Writes go to a temporary file in the target folder, are flushed to disk, then renamed into place:
  a reader never sees half a file.
- The root folder is created with owner-only permissions where the OS supports them.
"""
import os
import re
import tempfile
import uuid
from pathlib import Path

from app.storage.base import FileNotAvailable

_KEY = re.compile(r"^[0-9a-f]{2}/[0-9a-f]{32}\.(jpg|png)$")
_EXTENSIONS = {".jpg", ".png"}


class LocalDiskStorage:
    scheme = "local"

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        if not _KEY.match(key or ""):
            raise FileNotAvailable("malformed storage key")
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise FileNotAvailable("storage key outside the storage root")
        return path

    def save(self, content: bytes, extension: str) -> str:
        if extension not in _EXTENSIONS:
            raise ValueError(f"unsupported extension {extension!r}")
        name = uuid.uuid4().hex
        key = f"{name[:2]}/{name}{extension}"
        target = self._path(key)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.parent.mkdir(mode=0o700, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".upload-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return key

    def open(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise FileNotAvailable("file missing") from None

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except FileNotAvailable:
            pass
