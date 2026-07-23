"""Phase 3: the full Schema deliberation loop, wired end to end.

Outer loop: observe -> deliberate -> execute -> record, with the append-only
Timeline as ground truth. Inner loop (one deliberation): theorize (rewrite
``world_model.py``) -> certify (backtest over ALL recorded reality) -> plan
(search inside the certified model) -> commit (the only channel to the
environment).

The discipline, exactly as in the plan:

- **Backtest gates planning.** The agent only plans while the model is green
  over everything ever recorded; a red model goes back to theorize first.
- **Mispredictions void plans.** After every committed action — and every
  observed opponent move — reality's observation is compared to ``step()``'s
  prediction. One mismatch aborts the current line of play and re-enters
  deliberation with a pointed counterexample (which, being recorded, the
  certification loop is forced to resolve).
- **Rejections indict the model too.** The backtest never calls
  ``legal_actions``, so reality refusing an action (or the model offering
  none when reality awaits a move) is live evidence the backtest cannot see;
  it is fed to the theorizer as explicit feedback.
- **Action for discovery.** During learning, an exploration mix sends some
  moves off the planner's line — random probes reach regions best play never
  visits (forced passes, endgame quirks), which is where latent rule errors
  and unresolved rulebook ambiguities hide.

Convergence (the Phase 3 exit criterion): a complete game played on a
previously certified model with zero deliberations, plus a green backtest
over every recorded game of the session — the model, built from the rulebook
alone, now predicts reality move for move.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .backtest import diff_paths
from .env import Environment, IllegalActionError, TransitionEvent
from .modelgen import certify
from .planner import Policy, alphabeta_policy
from .sandbox import SandboxedModel, SandboxError
from .timeline import Timeline

Theorizer = Callable[[Path, list[Path], str | None, str, str], None]
"""theorize(game_dir, timeline_paths, start_code, trigger, detail).

Must leave ``game_dir/world_model.py`` green over ``timeline_paths`` (raise
if it cannot). ``start_code`` is None when no model exists yet. ``trigger``
is one of: no-model, red-backtest, misprediction, model-error, rejection,
no-actions, score.
"""


def claude_theorizer(game_dir: Path, timeline_paths: list[Path],
                     start_code: str | None, trigger: str, detail: str) -> None:
    """Default theorizer: Claude-backed generation/repair (see modelgen)."""
    from .modelgen import generate_model, repair_with_feedback

    if start_code is None:
        generate_model(game_dir, timeline_paths)
    elif trigger in ("rejection", "no-actions"):
        # Not visible to the backtest — must reach the repair prompt directly.
        repair_with_feedback(game_dir, timeline_paths, detail)
    else:
        # The counterexample is in the Timeline; certification will surface it.
        generate_model(game_dir, timeline_paths, start_code=start_code)


@dataclass
class Deliberation:
    trigger: str
    detail: str


@dataclass
class GameReport:
    timeline_path: Path
    moves: int = 0            # agent actions accepted by reality
    transitions: int = 0      # all recorded reality transitions (both seats)
    mispredictions: int = 0
    rejections: int = 0
    deliberations: list[Deliberation] = field(default_factory=list)
    scores: dict[int, float] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        """True if the whole game ran on the standing model, never repaired."""
        return not self.deliberations

    def summary(self) -> str:
        return (f"moves={self.moves} transitions={self.transitions} "
                f"deliberations={len(self.deliberations)} "
                f"mispredictions={self.mispredictions} rejections={self.rejections} "
                f"scores={self.scores}")


def exploit_policy(depth: int = 3) -> Policy:
    """Alpha-beta inside the certified model, using its heuristic() if present."""

    def policy(model, state, player):
        use_h = isinstance(model, SandboxedModel) and model.supports("heuristic")
        heuristic = (lambda m, s, p: m.heuristic(s, p)) if use_h else None
        return alphabeta_policy(depth, heuristic)(model, state, player)

    return policy


def explore_mix(base: Policy, explore_rate: float, rng: random.Random) -> Policy:
    """Action-for-discovery mix: sometimes probe off the planner's line."""

    def policy(model, state, player):
        actions = model.legal_actions(state, player)
        if len(actions) > 1 and rng.random() < explore_rate:
            return rng.choice(actions)
        return base(model, state, player)

    return policy


def _last_observation(timeline: Timeline) -> dict | None:
    obs = None
    for entry in timeline:
        obs = entry.get("observation", obs)
    return obs


def _record(timeline: Timeline, event: TransitionEvent) -> None:
    timeline.append("transition", player=event.player, action=event.action,
                    observation=event.observation)


def _replay(model: SandboxedModel, timeline: Timeline) -> dict:
    """Re-derive the current state by replaying this game's record through the
    model — how the agent recovers its position after a mid-game repair."""
    state: dict | None = None
    for entry in timeline:
        if entry["type"] == "init":
            state = model.initial_state(entry.get("config", {}))
        elif entry["type"] == "transition":
            state = model.step(state, entry["action"])
    if state is None:
        raise RuntimeError("timeline has no init entry")
    return state


def _check_events(model: SandboxedModel, state: dict,
                  events: list[TransitionEvent]) -> tuple[dict | None, str | None]:
    """Advance ``state`` through observed reality, checking every prediction.

    Returns ``(new_state, None)`` if the model predicted every observation, or
    ``(None, counterexample)`` on the first mismatch (which by then is already
    recorded, so certification must resolve it).
    """
    for event in events:
        try:
            state = model.step(state, event.action)
            predicted = model.observation(state, None)
        except SandboxError as exc:
            return None, (f"model failed on observed real transition "
                          f"(player {event.player}, action {event.action!r}): {exc}")
        paths = diff_paths(event.observation, predicted)
        if paths:
            return None, (
                f"live misprediction at {', '.join(paths)}\n"
                f"  player {event.player} took action {event.action!r}\n"
                f"  reality:   {event.observation}\n"
                f"  predicted: {predicted}")
    return state, None


def play_game(env: Environment, game_dir: str | Path, timeline_path: str | Path,
              past_timelines: list[Path] | None = None,
              theorizer: Theorizer = claude_theorizer,
              policy: Policy | None = None,
              call_timeout: float = 60.0,
              max_deliberations: int = 8,
              max_moves: int = 1000,
              verbose: bool = True) -> GameReport:
    """Play one real game under the full Schema discipline. Returns a report;
    raises RuntimeError if the deliberation budget runs out."""
    game_dir = Path(game_dir)
    model_path = game_dir / "world_model.py"
    timeline = Timeline(timeline_path)
    if len(timeline):
        raise ValueError(f"{timeline.path} already holds a recorded game — "
                         f"a timeline is the record of one real game")
    policy = policy or exploit_policy()
    all_paths = [timeline.path] + [Path(p) for p in (past_timelines or [])]
    report = GameReport(timeline_path=timeline.path)

    config, initial_obs, events = env.reset()
    timeline.append("init", config=config, observation=initial_obs)
    for event in events:
        _record(timeline, event)
    report.transitions += len(events)

    model: SandboxedModel | None = None
    state: dict | None = None

    def say(msg: str) -> None:
        if verbose:
            print(msg)

    def deliberate(trigger: str, detail: str) -> None:
        """Theorize + certify. Leaves a green model on disk (or raises)."""
        nonlocal model
        if len(report.deliberations) >= max_deliberations:
            raise RuntimeError(
                f"deliberation budget ({max_deliberations}) exhausted; "
                f"last trigger: {trigger}\n{detail}")
        report.deliberations.append(Deliberation(trigger, detail))
        say(f"  deliberation {len(report.deliberations)} [{trigger}]: "
            f"{detail.splitlines()[0]}")
        if model is not None:
            model.close()
            model = None
        start_code = (model_path.read_text(encoding="utf-8")
                      if model_path.exists() else None)
        theorizer(game_dir, all_paths, start_code, trigger, detail)

    def reopen() -> None:
        """Fresh sandbox on the (re)certified model; recover position."""
        nonlocal model, state
        if model is not None:
            model.close()
        model = SandboxedModel(model_path, call_timeout=call_timeout)
        state = _replay(model, timeline)

    # Certify before the first plan: backtest gates planning.
    if not model_path.exists():
        deliberate("no-model", "no world_model.py yet — generate one from the "
                               "rules spec and the reality recorded so far")
    else:
        green, detail = certify(model_path, all_paths, call_timeout=call_timeout)
        if not green:
            deliberate("red-backtest", detail)
    reopen()

    try:
        while not env.is_terminal():
            if report.moves >= max_moves:
                raise RuntimeError(f"game exceeded {max_moves} agent moves")

            # plan — only inside the certified model
            try:
                actions = model.legal_actions(state, env.agent_seat)
            except SandboxError as exc:
                deliberate("model-error", f"legal_actions failed: {exc}")
                reopen()
                continue
            if not actions:
                last_obs = _last_observation(timeline)
                deliberate("no-actions",
                           f"Live play failure: reality awaits our move (player "
                           f"{env.agent_seat}) but legal_actions() returned none. "
                           f"Current recorded observation: {last_obs}")
                reopen()
                continue
            action = policy(model, state, env.agent_seat)

            # commit — the only channel to reality
            try:
                events = env.act(action)
            except IllegalActionError as exc:
                timeline.append("log", raw={"rejected_action": action,
                                            "player": env.agent_seat,
                                            "error": str(exc)})
                report.rejections += 1
                last_obs = _last_observation(timeline)
                deliberate("rejection",
                           f"Live play failure: reality REJECTED action {action!r} "
                           f"({exc}) which legal_actions() offered — the model's "
                           f"precondition for it is wrong. Current recorded "
                           f"observation: {last_obs}")
                reopen()
                continue
            report.moves += 1

            # record first — reality enters the Timeline unconditionally —
            # then check every prediction against it
            for event in events:
                _record(timeline, event)
            report.transitions += len(events)
            new_state, counterexample = _check_events(model, state, events)
            if counterexample is not None:
                report.mispredictions += 1
                deliberate("misprediction", counterexample)
                reopen()
            else:
                state = new_state

        # game over: final scores are ground truth too
        report.scores = env.scores()
        timeline.append("result",
                        scores={str(p): s for p, s in report.scores.items()})
        green, detail = certify(model_path, all_paths, call_timeout=call_timeout)
        if not green:
            deliberate("score", detail)
        return report
    finally:
        if model is not None:
            model.close()


@dataclass
class SessionReport:
    session_dir: Path
    reports: list[GameReport] = field(default_factory=list)
    converged_at: int | None = None   # 1-based game index of the first clean game

    @property
    def converged(self) -> bool:
        return self.converged_at is not None

    def summary(self) -> str:
        games = len(self.reports)
        if self.converged:
            return (f"CONVERGED after {self.converged_at} games: game "
                    f"{self.converged_at} ran clean on the standing model and "
                    f"the backtest is green over all {games} recorded games")
        return f"not converged after {games} games"


def run_session(game_dir: str | Path,
                env_factory: Callable[[int], Environment],
                max_games: int = 8,
                theorizer: Theorizer = claude_theorizer,
                policy_factory: Callable[[int], Policy] | None = None,
                session_dir: str | Path | None = None,
                explore_rate: float = 0.3,
                depth: int = 3,
                base_seed: int = 0,
                call_timeout: float = 60.0,
                max_deliberations: int = 8,
                verbose: bool = True) -> SessionReport:
    """Play games until convergence (or ``max_games``).

    Exploration stays on while the model is still being falsified; a clean
    game — no deliberations at all, on a model certified before the game
    began — ends the session as converged.
    """
    game_dir = Path(game_dir)
    if session_dir is None:
        sessions = game_dir / "sessions"
        n = 0
        while (sessions / f"s{n:03d}").exists():
            n += 1
        session_dir = sessions / f"s{n:03d}"
    session_dir = Path(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)

    if policy_factory is None:
        def policy_factory(i: int) -> Policy:
            rng = random.Random(base_seed * 7919 + i)
            return explore_mix(exploit_policy(depth), explore_rate, rng)

    session = SessionReport(session_dir=session_dir)
    past: list[Path] = []
    for i in range(max_games):
        path = session_dir / f"game_{i:03d}.jsonl"
        if verbose:
            print(f"== game {i + 1}/{max_games} ({path.name}) ==")
        report = play_game(env_factory(i), game_dir, path,
                           past_timelines=past, theorizer=theorizer,
                           policy=policy_factory(i), call_timeout=call_timeout,
                           max_deliberations=max_deliberations, verbose=verbose)
        session.reports.append(report)
        past.append(path)
        if verbose:
            print(f"  {report.summary()}")
        if report.clean:
            session.converged_at = i + 1
            break
    if verbose:
        print(session.summary())
    return session
