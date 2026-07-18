"""Subprocess side of the sandbox. Not imported by the harness process.

Usage: python -m playharness._sandbox_runner <world_model.py>

Applies resource limits and import restrictions, loads the model file, then
serves JSON-lines requests on stdin:

    {"id": 1, "op": "step", "args": [<state>, <action>]}

replying on stdout:

    {"id": 1, "ok": true, "result": <state'>}
    {"id": 1, "ok": false, "error": "ValueError('illegal move')"}

This is defense-in-depth against buggy or runaway generated code (accidental
file writes, os.system calls, infinite loops, memory blowups), not a hard
security boundary against an adversarial author.
"""

from __future__ import annotations

import builtins
import importlib
import json
import resource
import sys

# Modules generated world models may import. Everything else is refused.
ALLOWED_IMPORTS = frozenset({
    "abc", "bisect", "collections", "copy", "dataclasses", "enum", "fractions",
    "functools", "heapq", "itertools", "json", "math", "operator", "random",
    "re", "string", "types", "typing",
})

CPU_SECONDS = 60
MEMORY_BYTES = 512 * 1024 * 1024


def _apply_limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_NOFILE, (8, 8))


def _restrict_environment() -> None:
    # Preload the whitelist so allowed imports resolve from sys.modules and
    # never trigger transitive imports of non-whitelisted internals (e.g.
    # `import random` pulling in `_io`/`os` on first load).
    for name in ALLOWED_IMPORTS:
        importlib.import_module(name)

    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".")[0]
        if root not in ALLOWED_IMPORTS:
            raise ImportError(f"import of {name!r} is not allowed in the model sandbox")
        return real_import(name, globals, locals, fromlist, level)

    def no_open(*args, **kwargs):
        raise PermissionError("open() is not allowed in the model sandbox")

    builtins.__import__ = guarded_import
    builtins.open = no_open


def _load_model(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    _restrict_environment()  # after reading the file, before running model code
    namespace: dict = {"__name__": "world_model", "__file__": path}
    exec(compile(source, path, "exec"), namespace)
    return namespace


def main() -> None:
    _apply_limits()
    model = _load_model(sys.argv[1])

    stdout = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        op, args = request["op"], request.get("args", [])
        try:
            if op == "ping":
                result = "pong"
            else:
                fn = model.get(op)
                if not callable(fn):
                    raise AttributeError(f"model has no function {op!r}")
                result = fn(*args)
            reply = {"id": request["id"], "ok": True, "result": result}
        except Exception as exc:
            reply = {"id": request["id"], "ok": False, "error": repr(exc)}
        stdout.write(json.dumps(reply) + "\n")
        stdout.flush()


if __name__ == "__main__":
    main()
