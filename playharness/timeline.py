"""Append-only Timeline: the immutable ground-truth record of everything that happened.

One JSONL file per game (``games/<game>/timeline.jsonl``). The agent may revise
hypotheses and notes, never this record — the API deliberately offers no way to
rewrite or delete entries. The backtest and prediction checks replay it.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterator


class Timeline:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq = sum(1 for _ in self.read()) if self.path.exists() else 0

    @property
    def seq(self) -> int:
        """Number of records appended so far."""
        return self._seq

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        """Append one record, stamping it with a sequence number and timestamp."""
        entry = {"seq": self._seq, "ts": time.time(), **record}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, sort_keys=False) + "\n")
        self._seq += 1
        return entry

    def read(self) -> Iterator[dict[str, Any]]:
        """Iterate over all records in append order."""
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def transitions(self) -> Iterator[dict[str, Any]]:
        """Iterate over just the recorded state transitions."""
        for rec in self.read():
            if rec.get("type") == "transition":
                yield rec
