"""The environment interface: what "reality" looks like to the agent loop.

Phase 3 wires the full Schema deliberation cycle against this interface; the
Phase 2 BGA adapter will implement the same one, so the agent loop does not
care whether reality is a Playwright-driven BGA table or an offline reference
model. Reality speaks only in observations and rejections — it never exposes
its internal state, its legal-action list, or its dynamics.

An environment hosts ONE game. The agent owns one seat; the environment plays
every other seat (on BGA: the actual opponents). After ``reset()`` and after
every ``act()``, the environment advances opponents until it is the agent's
turn or the game is over, reporting each opponent move as an observed
:class:`TransitionEvent` — the equivalent of BGA's per-move notifications.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol

from .model_api import WorldModel
from .planner import Policy, random_policy


class IllegalActionError(Exception):
    """Reality refused the committed action. Carries no hint of what *would*
    be legal — the agent's model must supply that, and a rejection indicts it."""


@dataclass
class TransitionEvent:
    """One observed real transition: ``player`` took ``action``, and reality
    then looked like ``observation`` (omniscient viewpoint for
    perfect-information games, matching the Timeline/backtest convention)."""

    player: int
    action: dict
    observation: dict


class Environment(Protocol):
    agent_seat: int

    def action_spec(self) -> str:
        """Describe the wire format actions must be committed in.

        The action encoding belongs to the interface, not to the game's
        hidden dynamics: on BGA it is fixed by the harness's own UI map, and
        the table visibly offers the legal opening moves before the first
        act. So declaring it is observation, not leaked rules — while the
        *preconditions and effects* of actions still have to be learned
        from recorded play."""
        ...

    def reset(self) -> tuple[dict, dict, list[TransitionEvent]]:
        """Start the game. Returns ``(config, initial_observation, events)``
        where ``events`` are opponent moves played before the agent's first
        turn (empty if the agent moves first)."""
        ...

    def act(self, action: dict) -> list[TransitionEvent]:
        """Commit the agent's action. Raises :class:`IllegalActionError` if
        reality rejects it (the game does not advance). Otherwise returns the
        agent's own transition followed by opponent transitions up to the
        agent's next turn or the end of the game."""
        ...

    def is_terminal(self) -> bool: ...

    def scores(self) -> dict[int, float]:
        """Final scores per player. Only valid once ``is_terminal()``."""
        ...


class ReferenceEnv:
    """Offline reality: a trusted reference model plus opponent policies.

    The BGA stand-in for Phase 3 development — same duties as the adapter
    (observe, act with rejection, report opponent moves), none of the browser.
    """

    def __init__(self, reference: WorldModel, agent_seat: int = 0,
                 opponent_policy: Policy | None = None, config: dict | None = None,
                 seed: int | None = None, max_moves: int = 1000):
        self.reference = reference
        self.agent_seat = agent_seat
        self.config = config or {}
        rng = random.Random(seed)
        self.opponent_policy = opponent_policy or (
            lambda m, s, p: random_policy(m, s, p, rng))
        self.max_moves = max_moves
        self._state: dict | None = None
        self._moves = 0
        self._seen_players: set[int] = {agent_seat}

    def action_spec(self) -> str:
        """The interface's opening offer: example actions in their exact wire
        format — what a player sees on the table before the first move."""
        state = self.reference.initial_state(self.config)
        mover = state.get("to_move")
        examples = ([] if mover is None
                    else self.reference.legal_actions(state, mover))
        return ("Actions are committed to the interface as JSON dicts. "
                "These are the exact actions the interface offers in the "
                f"opening position (encoding is fixed): {examples[:6]}")

    def reset(self) -> tuple[dict, dict, list[TransitionEvent]]:
        self._state = self.reference.initial_state(self.config)
        self._moves = 0
        return (self.config,
                self.reference.observation(self._state, None),
                self._advance_opponents())

    def act(self, action: dict) -> list[TransitionEvent]:
        state = self._require_state()
        if self.reference.is_terminal(state):
            raise IllegalActionError("the game is over")
        if state["to_move"] != self.agent_seat:
            raise IllegalActionError("it is not your turn")
        if action not in self.reference.legal_actions(state, self.agent_seat):
            raise IllegalActionError(f"illegal action: {action!r}")
        self._state = self.reference.step(state, action)
        self._moves += 1
        own = TransitionEvent(self.agent_seat, action,
                              self.reference.observation(self._state, None))
        return [own] + self._advance_opponents()

    def is_terminal(self) -> bool:
        return self.reference.is_terminal(self._require_state())

    def scores(self) -> dict[int, float]:
        state = self._require_state()
        if not self.reference.is_terminal(state):
            raise RuntimeError("scores() before the game is over")
        players = {self.agent_seat} | self._seen_players
        return {p: self.reference.score(state, p) for p in sorted(players)}

    # -- internals ------------------------------------------------------------

    def _require_state(self) -> dict:
        if self._state is None:
            raise RuntimeError("environment not reset")
        return self._state

    def _advance_opponents(self) -> list[TransitionEvent]:
        events: list[TransitionEvent] = []
        state = self._require_state()
        while (not self.reference.is_terminal(state)
               and state["to_move"] != self.agent_seat):
            if self._moves >= self.max_moves:
                raise RuntimeError(f"game exceeded {self.max_moves} moves")
            mover = state["to_move"]
            self._seen_players.add(mover)
            action = self.opponent_policy(self.reference, state, mover)
            state = self.reference.step(state, action)
            self._moves += 1
            events.append(TransitionEvent(
                mover, action, self.reference.observation(state, None)))
        self._state = state
        return events
