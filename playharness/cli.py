"""Command-line entry points.

- ``selfplay``  — offline: play the world model against itself (no BGA, no network)
- ``bga-login`` — authenticate once and persist the browser session
- ``bga-probe`` — dump a table's raw gamedatas + screenshot (UI-map building aid)
- ``bga-play``  — play a game on a live BGA table with per-step prediction checks
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from pathlib import Path

from . import model_api
from .plan import simple
from .timeline import Timeline
from .types import PredictionMismatch


def _game_dir(game: str) -> Path:
    return model_api.games_dir() / game


# -- selfplay ----------------------------------------------------------------

def cmd_selfplay(args: argparse.Namespace) -> int:
    model = model_api.load_model(args.game)
    rng = random.Random(args.seed)
    wins = {"search": 0, "opponent": 0, "draw": 0}
    for game_index in range(args.games):
        search_color = "black" if game_index % 2 == 0 else "white"
        state = model.initial_state(None)
        while not model.is_terminal(state):
            player = state["to_move"]
            if player == search_color:
                action = simple.choose_action(model, state, player, depth=args.depth, rng=rng)
            elif args.opponent == "random":
                action = simple.random_action(model, state, player, rng=rng)
            else:
                action = simple.choose_action(model, state, player, depth=args.opponent_depth, rng=rng)
            state = model.step(state, action)
        other = "white" if search_color == "black" else "black"
        diff = model.score(state, search_color) - model.score(state, other)
        wins["search" if diff > 0 else "opponent" if diff < 0 else "draw"] += 1
        print(
            f"game {game_index + 1}: search({search_color}) "
            f"{model.score(state, search_color):.0f} - {model.score(state, other):.0f}"
        )
    print(f"\nsearch depth={args.depth} vs {args.opponent}: {wins}")
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


def cmd_bga_probe(args: argparse.Namespace) -> int:
    from .bga import observe as obs_mod
    from .bga import table as table_mod

    with _make_session() as session:
        session.ensure_logged_in()
        table_mod.goto_table(session.page, session.config.base_url, args.table)
        raw = obs_mod.snapshot(session.page, reload=False)
        out = Path(args.out) if args.out else None
        text = json.dumps(raw, indent=2, default=str)
        if out:
            out.write_text(text, encoding="utf-8")
            print(f"raw snapshot written to {out}")
        else:
            print(text)
        screenshot = obs_mod.save_screenshot(
            session.page, _game_dir(raw.get("game_name") or "unknown") / "screenshots", "probe"
        )
        print(f"screenshot: {screenshot}", file=sys.stderr)
    return 0


def cmd_bga_play(args: argparse.Namespace) -> int:
    from .bga import table as table_mod
    from .bga.adapter import BGAAdapter
    from .bga.ui_map import UIMap

    game = args.game
    game_dir = _game_dir(game)
    model = model_api.load_model(game)
    ui_map = UIMap.load(game_dir / "ui_map.json")
    timeline = Timeline(game_dir / "timeline.jsonl")
    rng = random.Random(args.seed)

    with _make_session() as session:
        session.ensure_logged_in()
        table_mod.goto_table(session.page, session.config.base_url, args.table)
        adapter = BGAAdapter(
            page=session.page,
            game=game,
            model=model,
            ui_map=ui_map,
            timeline=timeline,
            screenshots_dir=game_dir / "screenshots",
        )
        timeline.append({"type": "session_start", "game": game, "table": args.table})

        moves_played = 0
        while moves_played < args.max_moves:
            observation = adapter.wait_for_turn(timeout_s=args.turn_timeout)
            if observation["game_over"]:
                print(f"game over. scores: {observation.get('scores')}")
                timeline.append(
                    {"type": "game_end", "scores": observation.get("scores"),
                     "viewer_color": observation.get("viewer_color")}
                )
                return 0
            color = observation["viewer_color"]
            action = simple.choose_action(
                model,
                {"board": observation["board"], "to_move": observation["to_move"]},
                color,
                depth=args.depth,
                rng=rng,
            )
            if action is None:
                print("no legal action for us; waiting (BGA should auto-skip)")
                continue
            print(f"move {moves_played + 1} as {color}: {action}")
            try:
                adapter.commit_action(action, observation)
            except PredictionMismatch as mismatch:
                # Phase 2 policy: reality outranks the model — halt and report.
                # Phase 3 turns this into automated model repair.
                print(f"PREDICTION MISMATCH — plan voided:\n  " + "\n  ".join(mismatch.mismatches))
                print("counterexample recorded to the Timeline; stopping.")
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
    p.add_argument("--seed", type=int, default=None)
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
