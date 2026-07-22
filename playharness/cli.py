"""Command-line entry points for the BGA adapter (Phase 2).

- ``selfplay``  — offline: play the certified world model against itself
- ``bga-login`` — authenticate once and persist the browser session
- ``bga-probe`` — dump a table's raw gamedatas + screenshot (UI-map building aid)
- ``bga-play``  — play a game on a live BGA table with per-step prediction checks

The Phase 1 learning pipeline has its own entry point:
``python -m playharness.learn <game>``.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from pathlib import Path

from .model_api import WorldModel, load_model
from .planner import Policy, alphabeta_policy, random_policy
from .timeline import Timeline

GAMES_DIR = Path(__file__).resolve().parent.parent / "games"


def _load_game_model(game: str) -> WorldModel:
    return load_model(str(GAMES_DIR / game / "world_model.py"), module_name=f"{game}_world_model")


def _search_policy(model: WorldModel, depth: int) -> Policy:
    heuristic = None
    if callable(getattr(model, "heuristic", None)):
        heuristic = lambda m, s, p: model.heuristic(s, p)
    return alphabeta_policy(depth, heuristic=heuristic)


# -- selfplay ----------------------------------------------------------------

def cmd_selfplay(args: argparse.Namespace) -> int:
    from .selfplay import play_game

    model = _load_game_model(args.game)
    rng = random.Random(args.seed)
    search = _search_policy(model, args.depth)
    opponent: Policy
    if args.opponent == "random":
        opponent = lambda m, s, p: random_policy(m, s, p, rng)
    else:
        opponent = _search_policy(model, args.opponent_depth)

    tally = {"search": 0, "opponent": 0, "draw": 0}
    for game_index in range(args.games):
        seat = game_index % 2
        result = play_game(model, {seat: search, 1 - seat: opponent}, max_moves=500)
        margin = result.scores[seat]
        tally["search" if margin > 0 else "opponent" if margin < 0 else "draw"] += 1
        print(f"game {game_index + 1}: search as player {seat}, margin {margin:+.0f}")
    print(f"\nsearch depth={args.depth} vs {args.opponent}: {tally}")
    return 0


# -- BGA commands ------------------------------------------------------------

def _make_session():
    from .bga.config import BGAConfig
    from .bga.session import BGASession

    return BGASession(BGAConfig.from_env())


def cmd_bga_login(args: argparse.Namespace) -> int:
    with _make_session() as session:
        session.ensure_logged_in()
        session.save_storage_state()
        print(f"session saved to {session.config.storage_state_path}")
    return 0


def cmd_bga_create(args: argparse.Namespace) -> int:
    from .bga import table as table_mod

    with _make_session() as session:
        session.ensure_logged_in()
        table_id = table_mod.create_table(
            session.page, args.game, mode=args.mode, force_manual=not args.auto_start
        )
        url = f"{session.config.base_url}/table?table={table_id}"
        print(f"created table {table_id}")
        print(f"  {url}")
        print("  seat a second player (a 2nd account or yourself), then run:")
        print(f"    python -m playharness bga-play {args.game} --table {table_id}")
    return 0


def cmd_bga_probe(args: argparse.Namespace) -> int:
    from .bga import observe as obs_mod
    from .bga import table as table_mod

    with _make_session() as session:
        session.ensure_logged_in()
        table_mod.goto_table(session.page, session.config.base_url, args.table)
        raw = obs_mod.snapshot(session.page, reload=False)
        text = json.dumps(raw, indent=2, default=str)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"raw snapshot written to {args.out}")
        else:
            print(text)
        game = raw.get("game_name") or "unknown"
        screenshot = obs_mod.save_screenshot(
            session.page, GAMES_DIR / game / "screenshots", "probe"
        )
        print(f"screenshot: {screenshot}", file=sys.stderr)
    return 0


def cmd_bga_play(args: argparse.Namespace) -> int:
    from .bga import table as table_mod
    from .bga.adapter import BGAAdapter, PredictionMismatch
    from .bga.ui_map import UIMap

    game = args.game
    game_dir = GAMES_DIR / game
    model = _load_game_model(game)
    ui_map = UIMap.load(game_dir / "ui_map.json")
    policy = _search_policy(model, args.depth)

    # One timeline file per real game, alongside the recorded ground-truth games.
    timeline_path = game_dir / "timelines" / f"bga_{int(time.time())}.jsonl"

    with _make_session() as session:
        session.ensure_logged_in()
        table_mod.goto_table(session.page, session.config.base_url, args.table)
        adapter = BGAAdapter(
            page=session.page,
            game=game,
            model=model,
            ui_map=ui_map,
            timeline=Timeline(timeline_path),
            screenshots_dir=game_dir / "screenshots",
        )
        print(f"recording to {timeline_path}")

        moves_played = 0
        while moves_played < args.max_moves:
            try:
                observation = adapter.wait_for_turn(timeout_s=args.turn_timeout)
                if observation["game_over"]:
                    print(f"game over. result: {observation.get('final_scores')} "
                          f"(BGA panel: {observation.get('scores_raw')})")
                    return 0
                player = observation["viewer_player"]
                action = policy(model, adapter.state, player)
                print(f"move {moves_played + 1} as player {player}: {action}")
                adapter.commit_action(action)
            except PredictionMismatch as mismatch:
                # Phase 2 policy: reality outranks the model — halt and report.
                # Phase 3 turns this into automated model repair.
                print(f"PREDICTION MISMATCH — plan voided: {mismatch}")
                print(f"counterexample recorded to {timeline_path}; stopping.")
                return 2
            moves_played += 1
        print(f"reached max-moves limit ({args.max_moves}); stopping")
        return 1


# -- parser ------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="playharness")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("selfplay", help="offline self-play using the world model only")
    p.add_argument("game", nargs="?", default="reversi")
    p.add_argument("--games", type=int, default=10)
    p.add_argument("--depth", type=int, default=3)
    p.add_argument("--opponent", choices=["random", "search"], default="random")
    p.add_argument("--opponent-depth", type=int, default=1)
    p.add_argument("--seed", type=int, default=None)
    p.set_defaults(func=cmd_selfplay)

    p = sub.add_parser("bga-login", help="log in to BGA and persist the session")
    p.set_defaults(func=cmd_bga_login)

    p = sub.add_parser("bga-create", help="create a new (manual) table and print its id/URL")
    p.add_argument("game", nargs="?", default="reversi")
    p.add_argument("--mode", choices=["realtime", "async"], default="async",
                   help="async (turn-based) suits the harness's reload-based play; "
                        "players need not be online simultaneously")
    p.add_argument("--auto-start", action="store_true",
                   help="allow the table to auto-start (default: manual, so it never "
                        "starts against a random opponent)")
    p.set_defaults(func=cmd_bga_create)

    p = sub.add_parser("bga-probe", help="dump raw gamedatas + screenshot from a table")
    p.add_argument("--table", required=True, help="table URL or numeric table id")
    p.add_argument("--out", help="write the raw snapshot JSON to this file")
    p.set_defaults(func=cmd_bga_probe)

    p = sub.add_parser("bga-play", help="play a live BGA table")
    p.add_argument("game", nargs="?", default="reversi")
    p.add_argument("--table", required=True, help="table URL or numeric table id")
    p.add_argument("--depth", type=int, default=4)
    p.add_argument("--max-moves", type=int, default=200)
    p.add_argument("--turn-timeout", type=float, default=600.0)
    p.set_defaults(func=cmd_bga_play)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
