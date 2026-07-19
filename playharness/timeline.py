"""Append-only Timeline: the immutable record of what actually happened.

One JSONL file per game session directory (``games/<game>/timeline.jsonl``).
Entries are appended and never rewritten — hypotheses and notes may be revised,
the record of reality may not. The backtest replays this file to certify a
world model.

Entry kinds (the ``type`` field):

    init        {"config": ..., "observation": ...}   # game start
    transition  {"player": ..., "action": ..., "observation": ...}
    log         {"raw": ...}                          # raw BGA game-log lines
    result      {"scores": {player: float, ...}}

Every entry gets a monotonically increasing ``seq`` and a wall-clock ``ts``
stamped at append time.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterator


class Timeline:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._next_seq = sum(1 for _ in self) if self.path.exists() else 0

    def append(self, type: str, **fields) -> dict:
        """Append one entry and flush it to disk. Returns the stored entry."""
        entry = {"seq": self._next_seq, "ts": time.time(), "type": type, **fields}
        line = json.dumps(entry, sort_keys=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
        self._next_seq += 1
        return entry

    def __iter__(self) -> Iterator[dict]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def __len__(self) -> int:
        return self._next_seq

    def entries(self, type: str | None = None) -> list[dict]:
        return [e for e in self if type is None or e["type"] == type]

    def transitions(self) -> list[dict]:
        return self.entries("transition")
