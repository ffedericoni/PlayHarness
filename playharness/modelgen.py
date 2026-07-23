"""Model generation: RulesSpec -> executable world_model.py, certified by backtest.

The Schema discipline, offline: Claude compiles the RulesSpec into a
``world_model.py``; the backtest replays every recorded transition through it;
any mismatch produces a counterexample that goes back to Claude for repair.
The rulebook text is evidence, but the recorded play outranks it.

Usage:
    python -m playharness.modelgen --game reversi
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import model_api
from .backtest import BacktestResult, run_backtest
from .sandbox import SandboxedModel, SandboxError
from .timeline import Timeline
from ._sandbox_runner import ALLOWED_IMPORTS

MODEL = "claude-opus-4-8"
MAX_REPAIR_ITERATIONS = 6
FORMAT_EXAMPLE_TRANSITIONS = 4


# --- Prompt construction ------------------------------------------------------

def _format_examples(timeline_path: Path) -> str:
    """Verbatim init + first few transitions: they define the observation
    and action encodings the generated model must reproduce exactly."""
    lines = []
    for entry in Timeline(timeline_path):
        if entry["type"] == "init":
            lines.append(f"Initial observation (config={json.dumps(entry['config'])}):")
            lines.append(json.dumps(entry["observation"]))
        elif entry["type"] == "transition":
            lines.append(f"Player {entry['player']} action {json.dumps(entry['action'])} ->")
            lines.append(json.dumps(entry["observation"]))
            if sum(1 for l in lines if l.startswith("Player")) >= FORMAT_EXAMPLE_TRANSITIONS:
                break
    return "\n".join(lines)


def build_generation_prompt(game_dir: Path, timeline_paths: list[Path],
                            extra_context: str | None = None) -> str:
    spec = (game_dir / "rules_spec.json").read_text(encoding="utf-8")
    ambiguities_path = game_dir / "ambiguities.md"
    ambiguities = (ambiguities_path.read_text(encoding="utf-8")
                   if ambiguities_path.exists() else "(none recorded)")
    live_context = ""
    if extra_context:
        live_context = f"""
Additional live context from the harness (the interface's declared action \
wire format outranks any encoding you might invent):

<live_context>
{extra_context}
</live_context>
"""

    return f"""\
You are writing the executable world model for a boardgame harness. Produce a \
single self-contained Python module implementing this contract exactly:

<contract>
{model_api.__doc__}
</contract>

Constraints on the module:
- It runs in a sandbox: only these stdlib imports are allowed: \
{", ".join(sorted(ALLOWED_IMPORTS))}. No file, network, or OS access.
- Module-level functions only; no classes required. Pure functions: `step` \
must not mutate its input.
- All states/observations/actions are plain JSON-serializable dicts/lists.

The game's rules, extracted from its rulebook:

<rules_spec>
{spec}
</rules_spec>

Known ambiguities in the rulebook (resolve them to match the recorded play \
below — recorded reality outranks any reading of the rulebook):

<ambiguities>
{ambiguities}
</ambiguities>

Recorded real play defines the EXACT observation and action encodings your \
model must reproduce (board representation, player numbering, turn handling):

<recorded_play_examples>
{_format_examples(timeline_paths[0])}
</recorded_play_examples>
{live_context}
Your model will be certified by replaying {len(timeline_paths)} full recorded \
games through `step()` and comparing `observation(state, None)` to every \
recorded observation byte-for-byte. Study the examples carefully — especially \
how the game encodes whose turn it is after each move, and what happens when \
a player cannot act.

Output ONLY the complete Python module in a single ```python code block."""


def build_repair_prompt(code: str, failure: str) -> str:
    return f"""\
Your world model failed certification against recorded real play. The recorded \
game is ground truth — your model must reproduce it exactly.

Current model:

```python
{code}
```

Certification failure:

{failure}

Diagnose the mismatch and fix the model. You may revise the transition rules \
or the state representation, but the recorded observations' encoding is fixed. \
Output ONLY the complete corrected Python module in a single ```python code \
block."""


def extract_code(text: str) -> str:
    blocks = re.findall(r"```python\n(.*?)```", text, re.DOTALL)
    if not blocks:
        raise ValueError("response contained no ```python code block")
    return blocks[-1].strip() + "\n"


# --- Certification ------------------------------------------------------------

def certify(model_path: Path, timeline_paths: list[Path],
            call_timeout: float = 30.0) -> tuple[bool, str]:
    """Backtest the generated model (in the sandbox) against every timeline.

    Returns (green, failure_description).
    """
    try:
        with SandboxedModel(model_path, call_timeout=call_timeout) as model:
            total = 0
            for path in timeline_paths:
                result: BacktestResult = run_backtest(model, Timeline(path))
                if not result.ok:
                    return False, f"[{path.name}] {result.describe()}"
                total += result.checked
        return True, f"backtest GREEN: {total} entries across {len(timeline_paths)} games"
    except SandboxError as exc:
        return False, f"model failed to load or run in the sandbox: {exc}"


# --- Generation loop ----------------------------------------------------------

def _ask(client, prompt: str) -> str:
    with client.messages.stream(
        model=MODEL,
        max_tokens=32000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        message = stream.get_final_message()
    return next(b.text for b in message.content if b.type == "text")


def generate_model(game_dir: str | Path, timeline_paths: list[Path],
                   max_iterations: int = MAX_REPAIR_ITERATIONS,
                   start_code: str | None = None,
                   extra_context: str | None = None) -> Path:
    """Generate + repair world_model.py until the backtest is green.

    ``start_code`` skips initial generation and enters the repair loop from
    existing code (used when a previously certified model goes red — e.g.
    after the backtest starts checking more of reality).
    Raises RuntimeError if certification is still red after the budget.
    """
    import anthropic

    game_dir = Path(game_dir)
    model_path = game_dir / "world_model.py"
    client = anthropic.Anthropic()

    if start_code is not None:
        code = start_code
    else:
        print("Generating world model from RulesSpec ...")
        code = extract_code(_ask(client, build_generation_prompt(
            game_dir, timeline_paths, extra_context=extra_context)))

    for iteration in range(1, max_iterations + 1):
        model_path.write_text(code, encoding="utf-8")
        green, detail = certify(model_path, timeline_paths)
        print(f"  iteration {iteration}: {detail.splitlines()[0]}")
        if green:
            return model_path
        if iteration == max_iterations:
            break
        code = extract_code(_ask(client, build_repair_prompt(code, detail)))

    raise RuntimeError(
        f"model still failing certification after {max_iterations} iterations; "
        f"last failure:\n{detail}")


def repair_with_feedback(game_dir: str | Path, timeline_paths: list[Path],
                         feedback: str) -> Path:
    """One repair call driven by live-play evidence the backtest cannot see.

    The backtest certifies ``step``/``observation``/``score`` against recorded
    reality, but never calls ``legal_actions`` — so a model that offers
    illegal moves (or none at all) can stay green while failing live play.
    Rejections from reality arrive here as ``feedback``; after the repair
    call, the normal certify/repair loop keeps the dynamics green.
    """
    import anthropic

    game_dir = Path(game_dir)
    model_path = game_dir / "world_model.py"
    code = model_path.read_text(encoding="utf-8")
    client = anthropic.Anthropic()

    print("Repairing from live-play feedback ...")
    new_code = extract_code(_ask(client, build_repair_prompt(code, feedback)))
    return generate_model(game_dir, timeline_paths, start_code=new_code)


def build_heuristic_prompt(code: str, spec: str, feedback: str | None) -> str:
    feedback_block = ""
    if feedback:
        feedback_block = f"""

A previous heuristic was evaluated in real games; use this feedback to write a
stronger one:

<feedback>
{feedback}
</feedback>"""

    return f"""\
This certified world model needs a strategy layer. Add ONE function to it:

    heuristic(state, player) -> float

It evaluates NON-TERMINAL states at alpha-beta search cutoffs (depth ~3), as
an estimate of the final score margin from `player`'s viewpoint. It must be
zero-sum symmetric (heuristic(s, a) == -heuristic(s, b)) and fast (called
thousands of times per move). Use real strategic knowledge of this game —
e.g. positional weights, mobility, stability — not just the raw current
score, which is known to be a weak mid-game signal in many games.

The game's rules:

<rules_spec>
{spec}
</rules_spec>

Current module (do NOT change any existing function — they are certified
against recorded play; only add heuristic and any private helpers it needs):

```python
{code}
```
{feedback_block}
Output ONLY the complete Python module (existing code + heuristic) in a
single ```python code block."""


def add_heuristic(game_dir: str | Path, timeline_paths: list[Path],
                  feedback: str | None = None) -> Path:
    """Ask Claude to add/improve heuristic() in world_model.py.

    Re-certifies afterwards — the strategy layer must not disturb the
    certified dynamics. Raises RuntimeError if it does and repair fails.
    """
    import anthropic

    game_dir = Path(game_dir)
    model_path = game_dir / "world_model.py"
    spec = (game_dir / "rules_spec.json").read_text(encoding="utf-8")
    code = model_path.read_text(encoding="utf-8")
    client = anthropic.Anthropic()

    print("Generating heuristic()" + (" (with game feedback)" if feedback else "") + " ...")
    new_code = extract_code(_ask(client, build_heuristic_prompt(code, spec, feedback)))
    model_path.write_text(new_code, encoding="utf-8")

    green, detail = certify(model_path, timeline_paths)
    print(f"  re-certification: {detail.splitlines()[0]}")
    if not green:
        # The strategy layer broke the dynamics — send it through repair.
        return generate_model(game_dir, timeline_paths, start_code=new_code)
    return model_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", required=True, help="Game name (dir under games/)")
    parser.add_argument("--max-iterations", type=int, default=MAX_REPAIR_ITERATIONS)
    args = parser.parse_args()

    game_dir = Path("games") / args.game
    timelines = sorted((game_dir / "timelines").glob("game_*.jsonl"))
    if not timelines:
        print(f"no recorded timelines in {game_dir / 'timelines'} — "
              f"run `python -m playharness.learn {args.game}` to record ground truth first",
              file=sys.stderr)
        return 1
    path = generate_model(game_dir, timelines)
    print(f"CERTIFIED: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
