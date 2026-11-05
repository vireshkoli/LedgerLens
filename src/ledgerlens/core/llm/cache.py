"""A file-per-response cache, keyed by a hash of the request.

Each response is its own JSON file, so CI can later replay a committed set of them, and writing
one never contends with writing another.
"""

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from ledgerlens.core.llm.contracts import Completion, LLMRequest

# Bump this if the meaning of a cached entry changes, so old entries stop matching.
CACHE_KEY_VERSION = 1

logger = logging.getLogger(__name__)


def cache_key(request: LLMRequest) -> str:
    """Hash everything that decides a response.

    Unset optional fields are left out, so adding one later doesn't invalidate existing entries.

    Args:
        request: The request.

    Returns:
        A SHA-256 hex digest.
    """
    payload = {
        "version": CACHE_KEY_VERSION,
        "request": request.model_dump(mode="json", exclude_none=True),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class ResponseCache:
    """Stores completions on disk."""

    def __init__(self, root: Path) -> None:
        """Set up a cache.

        Args:
            root: The folder that holds the entries. It's created on the first write.
        """
        self._root = root

    def _path(self, key: str) -> Path:
        return self._root / key[:2] / f"{key}.json"

    def get(self, key: str) -> Completion | None:
        """Read an entry.

        A damaged entry counts as a miss: a repeat call costs a little, and serving a damaged
        response could put a wrong answer into a result.

        Args:
            key: From `cache_key`.

        Returns:
            The stored completion, or None if there's no usable entry.
        """
        try:
            return Completion.model_validate_json(self._path(key).read_bytes())
        except FileNotFoundError:
            return None
        except ValidationError:
            logger.warning("ignoring damaged cache entry %s", key)
            return None

    def put(self, key: str, completion: Completion) -> None:
        """Write an entry.

        The rename is atomic, so a crash or a parallel reader never sees half a file.

        Args:
            key: From `cache_key`.
            completion: The completion to keep.
        """
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(completion.model_dump_json())
        Path(temporary).replace(path)
