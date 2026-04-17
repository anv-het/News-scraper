"""
Persistent unique ID allocation for news articles.

Sequence:
  A00000 ... A99999, B00000 ... Z99999, ZA00000 ...
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path


class UniqueIdAllocator:
    """Thread-safe allocator that persists sequence state to disk."""

    def __init__(self, state_path: str | Path):
        self._state_path = Path(state_path)
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._prefix_index = 0
        self._number = 0
        self._load_state()

    @staticmethod
    def _suffix_from_index(index: int) -> str:
        chars: list[str] = []
        value = index
        while True:
            value, rem = divmod(value, 26)
            chars.append(chr(ord("A") + rem))
            value -= 1
            if value < 0:
                break
        return "".join(reversed(chars))

    @classmethod
    def _prefix_from_index(cls, index: int) -> str:
        if index < 26:
            return chr(ord("A") + index)
        return "Z" + cls._suffix_from_index(index - 26)

    @classmethod
    def _format_id(cls, prefix_index: int, number: int) -> str:
        return f"{cls._prefix_from_index(prefix_index)}{number:05d}"

    def _load_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            prefix_index = int(data.get("prefix_index", 0))
            number = int(data.get("number", 0))
            if prefix_index < 0 or number < 0 or number >= 100000:
                return
            self._prefix_index = prefix_index
            self._number = number
        except Exception:
            return

    def _save_state_locked(self) -> None:
        payload = {
            "prefix_index": self._prefix_index,
            "number": self._number,
        }

        fd, tmp_path = tempfile.mkstemp(dir=str(self._state_path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
            os.replace(tmp_path, self._state_path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _next_id_locked(self) -> str:
        value = self._format_id(self._prefix_index, self._number)
        self._number += 1
        if self._number >= 100000:
            self._number = 0
            self._prefix_index += 1
        return value

    def assign_if_missing(self, items: list[dict]) -> int:
        """Assign unique_id in-place for items missing it and return assigned count."""
        if not items:
            return 0

        assigned = 0
        with self._lock:
            for item in items:
                if not isinstance(item, dict):
                    continue
                existing = str(item.get("unique_id") or "").strip()
                if existing:
                    continue
                item["unique_id"] = self._next_id_locked()
                assigned += 1

            if assigned:
                self._save_state_locked()

        return assigned
