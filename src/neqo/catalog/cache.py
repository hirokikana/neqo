from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MetadataCache:
    """Best-effort disk cache with atomic writes and a process-local hot cache."""

    def __init__(self, namespace: str, *, directory: str | Path | None = None, ttl: float = 300):
        if ttl < 0:
            raise ValueError("Cache TTL cannot be negative")
        root = (
            Path(directory)
            if directory
            else Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "neqo"
        )
        self.path = root / hashlib.sha256(namespace.encode()).hexdigest()
        self.ttl = ttl
        self._memory: dict[str, dict[str, Any]] = {}
        self._invalidated_at = 0.0

    def get(self, key: str, loader: Callable[[], Any]) -> Any:
        filename = self.path / (hashlib.sha256(key.encode()).hexdigest() + ".json")
        entry = self._memory.get(key)
        if entry is None:
            try:
                entry = json.loads(filename.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                entry = None
        if (
            isinstance(entry, dict)
            and isinstance(entry.get("created"), (float, int))
            and entry["created"] >= self._invalidated_at
            and 0 <= time.time() - entry["created"] < self.ttl
            and "value" in entry
        ):
            self._memory[key] = entry
            return entry["value"]
        value = loader()
        entry = {"created": time.time(), "value": value}
        self._memory[key] = entry
        temporary = None
        try:
            self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.NamedTemporaryFile(mode="w", dir=self.path, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(entry, stream)
            temporary.replace(filename)
        except (OSError, TypeError):
            logger.debug("Metadata disk cache unavailable; using process memory")
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    logger.debug("Metadata temporary file cleanup unavailable")
        return value

    def clear(self) -> None:
        self._invalidated_at = time.time()
        self._memory.clear()
        try:
            for filename in self.path.glob("*.json"):
                filename.unlink(missing_ok=True)
        except OSError:
            logger.debug("Metadata disk cache could not be cleared")
