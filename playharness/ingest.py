"""Rulebook ingestion: rulebook document -> structured RulesSpec + ambiguity log.

The RulesSpec is the *initial theory* — precise enough to generate an
executable world model from, but every claim in it remains subject to
certification against recorded play. The ambiguity pass lists everything the
rulebook underdetermines; these are hypotheses to test, not assumptions.

Usage:
    python -m playharness.ingest games/reversi/rulebook.md --game reversi
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field

MODEL = "claude-opus-4-8"


# --- RulesSpec schema ---------------------------------------------------------

class PlayerCount(BaseModel):
    min: int
    max: int


class ActionSpec(BaseModel):
    name: str = Field(description="Short identifier, e.g. 'place_disc'")
    preconditions: str = Field(description="Exactly when this action is legal")
    effects: str = Field(description="Precise state changes the action causes")
    forced: bool = Field(description="True if the player must take it when available")


class RulesSpec(BaseModel):
    """Structured extraction of a boardgame rulebook."""

    game_name: str
    players: PlayerCount
    setup: str = Field(description="Components and exact initial state, including who moves first")
    turn_structure: str = Field(description="Turn order, phases, and how the next player to move is determined — including what happens when a player cannot act")
    actions: list[ActionSpec]
    objective: str = Field(description="Win/loss/draw conditions and how the final score is computed")
    randomness: str = Field(description="All sources of chance (dice, shuffles, draws), or 'none'")
    hidden_information: str = Field(description="What each player cannot see, or 'none — perfect information'")
    edge_cases: list[str] = Field(description="Ties, forced passes, unusual interactions the rulebook calls out")


AMBIGUITY_PROMPT = """\
You previously extracted a structured RulesSpec from this rulebook. Now list \
every point where the rulebook UNDERDETERMINES behavior — places where a \
programmer implementing the game engine would have to make a choice the text \
does not fully dictate. For each ambiguity give: (1) the question, (2) the \
plausible interpretations, (3) a concrete experiment or observation of real \
play that would discriminate between them. Typical sources: exact encoding of \
passes/forfeited turns, scoring conventions, simultaneous-condition edge \
cases, and anything the rulebook describes only by example.

Output plain markdown with one '## ' section per ambiguity. Be exhaustive but \
concrete — these become hypotheses to test against recorded real play, not \
prose for humans."""


# --- Extraction ---------------------------------------------------------------

def _rulebook_content(path: Path) -> list[dict]:
    """Build the user-content blocks for a rulebook file (PDF or text)."""
    if path.suffix.lower() == ".pdf":
        data = base64.standard_b64encode(path.read_bytes()).decode()
        return [{"type": "document",
                 "source": {"type": "base64", "media_type": "application/pdf", "data": data}}]
    return [{"type": "text",
             "text": f"<rulebook>\n{path.read_text(encoding='utf-8')}\n</rulebook>"}]


def extract_rules_spec(client, rulebook_path: Path) -> RulesSpec:
    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        messages=[{
            "role": "user",
            "content": _rulebook_content(rulebook_path) + [{
                "type": "text",
                "text": ("Extract this boardgame rulebook into the given schema. "
                         "Be precise and complete — the spec will be compiled into an "
                         "executable game engine, so 'effects' and 'preconditions' must "
                         "be exact, not summaries."),
            }],
        }],
        output_format=RulesSpec,
    )
    return response.parsed_output


def extract_ambiguities(client, rulebook_path: Path, spec: RulesSpec) -> str:
    with client.messages.stream(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        messages=[{
            "role": "user",
            "content": _rulebook_content(rulebook_path) + [
                {"type": "text", "text": f"<rules_spec>\n{spec.model_dump_json(indent=2)}\n</rules_spec>"},
                {"type": "text", "text": AMBIGUITY_PROMPT},
            ],
        }],
    ) as stream:
        message = stream.get_final_message()
    return next(b.text for b in message.content if b.type == "text")


def ingest(rulebook_path: str | Path, game_dir: str | Path, force: bool = False) -> Path:
    """Run the full ingestion; writes rules_spec.json + ambiguities.md."""
    import anthropic

    rulebook_path, game_dir = Path(rulebook_path), Path(game_dir)
    spec_path = game_dir / "rules_spec.json"
    if spec_path.exists() and not force:
        print(f"{spec_path} already exists (use --force to redo)")
        return spec_path

    client = anthropic.Anthropic()
    print(f"Extracting RulesSpec from {rulebook_path} ...")
    spec = extract_rules_spec(client, rulebook_path)
    spec_path.write_text(spec.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"  wrote {spec_path}")

    print("Extracting ambiguity log ...")
    ambiguities = extract_ambiguities(client, rulebook_path, spec)
    (game_dir / "ambiguities.md").write_text(ambiguities + "\n", encoding="utf-8")
    print(f"  wrote {game_dir / 'ambiguities.md'}")
    return spec_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rulebook", help="Path to the rulebook (.pdf, .md, or .txt)")
    parser.add_argument("--game", required=True, help="Game name (dir under games/)")
    parser.add_argument("--force", action="store_true", help="Re-extract even if spec exists")
    args = parser.parse_args()
    ingest(args.rulebook, Path("games") / args.game, force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
