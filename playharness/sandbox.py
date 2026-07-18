"""Harness-side proxy for a world model running in a restricted subprocess.

Generated ``world_model.py`` files are model-written code: they get no
filesystem or network access, a stdlib-only import whitelist, and CPU/memory
limits (see :mod:`playharness._sandbox_runner`). The proxy exposes the same
six-function interface as an in-process model, so the backtest, planner, and
self-play code do not care which kind they are given.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
from pathlib import Path


class SandboxError(RuntimeError):
    """The sandboxed model raised, timed out, or died."""


class ModelTimeout(SandboxError):
    """A call exceeded its wall-clock budget; the subprocess was killed."""


class SandboxedModel:
    """Runs a world-model file in a sandbox subprocess and proxies calls to it.

    Satisfies :class:`playharness.model_api.WorldModel`. Use as a context
    manager or call :meth:`close` when done.
    """

    def __init__(self, model_path: str | Path, call_timeout: float = 10.0):
        self.model_path = str(model_path)
        self.call_timeout = call_timeout
        self._next_id = 0
        self._buffer = b""
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "playharness._sandbox_runner", self.model_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        # Fail fast on models that die at import (banned imports, syntax errors).
        self._call("ping", timeout=self.call_timeout)

    # -- world-model interface ------------------------------------------------

    def initial_state(self, config: dict) -> dict:
        return self._call("initial_state", config)

    def legal_actions(self, state: dict, player: int) -> list:
        return self._call("legal_actions", state, player)

    def step(self, state: dict, action: dict) -> dict:
        return self._call("step", state, action)

    def is_terminal(self, state: dict) -> bool:
        return self._call("is_terminal", state)

    def score(self, state: dict, player: int) -> float:
        return self._call("score", state, player)

    def observation(self, state: dict, player: int | None) -> dict:
        return self._call("observation", state, player)

    # -- plumbing -------------------------------------------------------------

    def _call(self, op: str, *args, timeout: float | None = None):
        if self._proc.poll() is not None:
            raise SandboxError(f"sandbox process is dead: {self._stderr_tail()}")
        timeout = self.call_timeout if timeout is None else timeout
        self._next_id += 1
        request = {"id": self._next_id, "op": op, "args": list(args)}
        try:
            self._proc.stdin.write((json.dumps(request) + "\n").encode())
            self._proc.stdin.flush()
        except BrokenPipeError:
            raise SandboxError(f"sandbox process died: {self._stderr_tail()}") from None

        line = self._read_line(timeout)
        reply = json.loads(line)
        if not reply.get("ok"):
            raise SandboxError(f"{op} failed in sandbox: {reply.get('error')}")
        return reply["result"]

    def _read_line(self, timeout: float) -> bytes:
        """Read one newline-terminated reply, enforcing a wall-clock budget."""
        import time

        deadline = time.monotonic() + timeout
        fd = self._proc.stdout.fileno()
        while b"\n" not in self._buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.close(kill=True)
                raise ModelTimeout(f"sandboxed call exceeded {timeout:.1f}s; process killed")
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                raise SandboxError(f"sandbox process closed stdout: {self._stderr_tail()}")
            self._buffer += chunk
        line, self._buffer = self._buffer.split(b"\n", 1)
        return line

    def _stderr_tail(self) -> str:
        if self._proc.stderr is None:
            return "<no stderr>"
        try:
            data = self._proc.stderr.read() or b""
        except Exception:
            return "<stderr unavailable>"
        return data.decode(errors="replace").strip()[-2000:] or "<empty stderr>"

    def close(self, kill: bool = False) -> None:
        if self._proc.poll() is None:
            if kill:
                self._proc.kill()
            else:
                self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()

    def __enter__(self) -> "SandboxedModel":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
