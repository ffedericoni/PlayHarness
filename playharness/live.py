"""Phase 3 pipeline: the full Schema loop against a live environment.

    python -m playharness.live reversi --fresh

Starting from only the rulebook, the agent plays real games (offline
``ReferenceEnv`` standing in for the Phase 2 BGA adapter, same interface),
records every transition to append-only timelines, checks every prediction,
repairs the model from counterexamples and rejections, and stops at
convergence: one full game with zero deliberations plus a green backtest
over every game the session recorded.

``--fresh`` deletes the existing ``world_model.py`` first (git keeps its
history) so the run genuinely starts from the rulebook alone — the honest
measurement of the Phase 3 exit criterion, games-to-green.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agent import run_session
from .env import ReferenceEnv
from .model_api import load_model


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("game", help="Game name (dir under games/), e.g. reversi")
    parser.add_argument("--games", type=int, default=8,
                        help="Give up if not converged after this many games")
    parser.add_argument("--depth", type=int, default=3, help="Alpha-beta depth")
    parser.add_argument("--explore", type=float, default=0.3,
                        help="Probability of an off-plan discovery move")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-deliberations", type=int, default=8,
                        help="Repair budget per game")
    parser.add_argument("--session", default=None,
                        help="Session dir name under games/<game>/sessions/ "
                             "(default: next free sNNN)")
    parser.add_argument("--fresh", action="store_true",
                        help="Delete the existing world_model.py first: start "
                             "from the rulebook alone (git keeps the old model)")
    args = parser.parse_args()

    game_dir = Path("games") / args.game

    print("== rulebook ingestion ==")
    if (game_dir / "rules_spec.json").exists():
        print("  rules_spec.json exists — reusing")
    else:
        rulebooks = [p for p in (game_dir / "rulebook.pdf", game_dir / "rulebook.md",
                                 game_dir / "rulebook.txt") if p.exists()]
        if not rulebooks:
            print(f"  ERROR: no rulebook found in {game_dir}", file=sys.stderr)
            return 1
        from .ingest import ingest
        ingest(rulebooks[0], game_dir)

    model_path = game_dir / "world_model.py"
    resumed = False
    if args.fresh and model_path.exists():
        model_path.unlink()
        print(f"--fresh: deleted {model_path} (history is in git)")
    elif model_path.exists():
        resumed = True
        print(f"NOTE: {model_path} exists and will be resumed; use --fresh for "
              f"a true from-rulebook-only run")

    reference_path = game_dir / "reference_model.py"
    if not reference_path.exists():
        print(f"  ERROR: no {reference_path} — the offline environment needs "
              f"a trusted reference model until the BGA adapter (Phase 2) "
              f"exists", file=sys.stderr)
        return 1
    reference = load_model(str(reference_path),
                           module_name=f"{args.game}_reference_model")

    def env_factory(i: int) -> ReferenceEnv:
        # Alternate seats so both colors' dynamics get exercised.
        return ReferenceEnv(reference, agent_seat=i % 2, seed=args.seed * 104729 + i)

    session_dir = (game_dir / "sessions" / args.session) if args.session else None
    print(f"== live session (env: reference model, agent alternates seats) ==")
    session = run_session(game_dir, env_factory, max_games=args.games,
                          session_dir=session_dir, explore_rate=args.explore,
                          depth=args.depth, base_seed=args.seed,
                          max_deliberations=args.max_deliberations)

    if session.converged:
        total = sum(r.transitions for r in session.reports)
        delibs = sum(len(r.deliberations) for r in session.reports)
        stats = (f"in {session.converged_at} games "
                 f"({total} transitions, {delibs} deliberations)")
        if resumed:
            print(f"CONVERGED {stats} — on a resumed model; run with --fresh "
                  f"to measure the from-rulebook-only exit criterion")
        else:
            print(f"PHASE 3 EXIT CRITERIA MET: green backtest from the "
                  f"rulebook alone {stats}")
        return 0
    print("Session ended without convergence — raise --games or inspect the "
          "last deliberations above", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
