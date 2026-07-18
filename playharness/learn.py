"""Phase 1 pipeline: rulebook -> RulesSpec -> certified world model -> planner check.

    python -m playharness.learn reversi

Steps (each skipped when its output already exists; --force redoes all):
  1. Record ground-truth timelines from the game's reference model
     (offline stand-in for BGA; see playharness/ground_truth.py).
  2. Ingest the rulebook into rules_spec.json + ambiguities.md   [needs API key]
  3. Generate world_model.py, repaired until the backtest is green [needs API key]
  4. Validate: alpha-beta planner (inside the certified model) vs a random
     player — the Phase 1 exit criterion is a >95% win rate.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from .ground_truth import ensure_ground_truth
from .planner import alphabeta_policy, random_policy
from .sandbox import SandboxedModel
from .selfplay import play_game


def validate_winrate(model, num_games: int = 20, depth: int = 3,
                     base_seed: int = 7, use_heuristic: bool = False) -> tuple[int, int, int]:
    """Alpha-beta planner vs seeded random player. Returns (wins, draws, losses)."""
    heuristic = (lambda m, s, p: m.heuristic(s, p)) if use_heuristic else None
    planner = alphabeta_policy(depth, heuristic)
    wins = draws = losses = 0
    for game in range(num_games):
        rng = random.Random(base_seed + game)
        rand = lambda m, s, p: random_policy(m, s, p, rng)
        seat = game % 2  # alternate colors
        result = play_game(model, {seat: planner, 1 - seat: rand})
        outcome = result.scores[seat]
        if outcome > 0:
            wins += 1
        elif outcome == 0:
            draws += 1
        else:
            losses += 1
        print(f"  game {game + 1}/{num_games}: "
              f"{'win' if outcome > 0 else 'draw' if outcome == 0 else 'LOSS'} "
              f"(score {outcome:+.0f} as {'first' if seat == 0 else 'second'} player)")
    return wins, draws, losses


def learn(game: str, num_timelines: int = 5, val_games: int = 40,
          val_depth: int = 3, force: bool = False) -> int:
    game_dir = Path("games") / game

    print(f"== 1/4 ground truth ({game}) ==")
    timelines = ensure_ground_truth(game_dir, num_games=num_timelines)
    print(f"  {len(timelines)} recorded games in {game_dir / 'timelines'}")

    print("== 2/4 rulebook ingestion ==")
    rulebooks = [p for p in (game_dir / "rulebook.pdf", game_dir / "rulebook.md",
                             game_dir / "rulebook.txt") if p.exists()]
    if not rulebooks:
        print(f"  ERROR: no rulebook found in {game_dir}", file=sys.stderr)
        return 1
    from .ingest import ingest
    ingest(rulebooks[0], game_dir, force=force)

    print("== 3/4 model generation + certification ==")
    model_path = game_dir / "world_model.py"
    if model_path.exists() and not force:
        from .modelgen import certify
        green, detail = certify(model_path, timelines)
        print(f"  existing model: {detail.splitlines()[0]}")
        if not green:
            print("  existing model is red — repairing from current code")
            from .modelgen import generate_model
            generate_model(game_dir, timelines,
                           start_code=model_path.read_text(encoding="utf-8"))
    else:
        from .modelgen import generate_model
        generate_model(game_dir, timelines)

    print(f"== 4/4 planner validation (alpha-beta depth {val_depth}, "
          f"{val_games} games vs random) ==")
    from .modelgen import add_heuristic
    for attempt in range(3):  # bare score -> heuristic -> improved heuristic
        with SandboxedModel(model_path, call_timeout=60.0) as model:
            use_h = model.supports("heuristic")
            print(f"  cutoff evaluation: {'heuristic()' if use_h else 'score() (no heuristic yet)'}")
            wins, draws, losses = validate_winrate(model, num_games=val_games,
                                                   depth=val_depth, use_heuristic=use_h)
        rate = wins / val_games
        print(f"  W/D/L = {wins}/{draws}/{losses}  (win rate {rate:.0%})")
        if rate > 0.95:
            print("PHASE 1 EXIT CRITERIA MET: green backtest + >95% win rate vs random")
            return 0
        if attempt == 2:
            break
        feedback = None
        if use_h:
            feedback = (f"With your current heuristic() the alpha-beta planner (depth "
                        f"{val_depth}) scored W/D/L = {wins}/{draws}/{losses} against a "
                        f"uniformly random opponent — it must win >95%. Losses mean the "
                        f"heuristic misjudges mid-game positions badly enough to lose "
                        f"even to random play.")
        add_heuristic(game_dir, timelines, feedback=feedback)

    print("Win rate below the 95% exit criterion after heuristic attempts — "
          "consider deeper search (see plan/ portfolio).", file=sys.stderr)
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("game", help="Game name (dir under games/), e.g. reversi")
    parser.add_argument("--timelines", type=int, default=5)
    parser.add_argument("--val-games", type=int, default=40)
    parser.add_argument("--val-depth", type=int, default=3)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    return learn(args.game, num_timelines=args.timelines, val_games=args.val_games,
                 val_depth=args.val_depth, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
