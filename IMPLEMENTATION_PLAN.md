# PlayHarness — Implementation Plan

A harness that uses Claude models to learn and play boardgames on [BoardGameArena](https://www.boardgamearena.com) (BGA). The harness determines each game's rules and objectives by reading its rulebook, builds an **executable world model** of the game, verifies that model against real play, and plans inside it.

Architecture inspired by [Schema](https://schema-harness.github.io/) ("Frontier Models with Our Harness Achieve ~99% on ARC-AGI-3 Public", Impossible Research, July 2026).

---

## 1. What we take from Schema

Schema's core insight: **the agent's latent world representation is a program, not a vector.** That makes it:

- **Interpretable** — a text file you can read and diff (`world_model.py`, `notes.md`)
- **Verifiable** — replayable against the recorded interaction history, belief by belief (`run_backtest`)
- **Searchable** — a program is a simulator; planning inside it costs zero real actions (`run_bfs`)

Schema's control structure, which we adopt directly:

- **Outer loop**: `observe → deliberate → execute → record`, with an **append-only Timeline** as immutable ground truth. The agent may revise hypotheses and notes, never the record of what happened.
- **Inner loop (one deliberation)**: `theorize (write_code) → certify (run_backtest) → plan (run_search) → commit (commit_actions)`. `commit_actions` is the *only* channel from thinking to action.
- **Reality outranks the model**: every real transition is checked against the model's prediction. One mismatch voids the current plan and forces a return to deliberation with the counterexample.
- **Action for discovery**: when multiple candidate rules fit the history, choose the action whose outcomes *discriminate* between them.
- **Joint state grounding + mechanism discovery**: the state representation and the transition rules live in one editable program, so a stubborn counterexample can indict the representation itself, not just the rule.
- **Persistent memory as the agent's "weights"**: `world_model.py`, `notes.md`, and the Timeline survive across levels/sessions.

### What differs for boardgames on BGA

| Dimension | ARC-AGI-3 (Schema) | Boardgames on BGA (this harness) |
|---|---|---|
| Rules | Hidden — must be induced from pixels | **Published** — a rulebook exists; induction becomes *verification* |
| Observation | Raw 64×64 grid | Structured DOM + screenshots + BGA game log |
| Opponent | None (single-agent puzzles) | **Adversarial**, often multiplayer |
| Determinism | Deterministic | Dice, shuffled decks, **hidden information** |
| Search | BFS to goal | Minimax / MCTS / expectimax with determinization |
| Objective | Inferred `is_goal()` | Stated in rulebook, encoded as `score()` / `is_terminal()` |

The rulebook is a head start, not the finish line: rulebooks are ambiguous prose, and BGA implements a *specific* interpretation (plus interface quirks). So the Schema discipline still applies — the rulebook produces the *initial theory*; every observed BGA transition either certifies or indicts it, and the backtest is the arbiter.

---

## 2. Architecture overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Agent Loop (Claude)                       │
│   Tool Runner: observe → deliberate → execute → record           │
│                                                                  │
│   deliberate = theorize → certify → plan → commit                │
└──────┬──────────────┬──────────────┬───────────────┬────────────┘
       │              │              │               │
┌──────▼─────┐ ┌──────▼──────┐ ┌────▼─────────┐ ┌───▼──────────┐
│  Rulebook   │ │ Game Model  │ │   Planner    │ │ BGA Adapter  │
│  Ingestion  │ │ (world_model│ │ (search in   │ │ (Playwright) │
│ PDF→rules   │ │  .py + back │ │  the model)  │ │ observe +    │
│  spec       │ │  test)      │ │              │ │ act + record │
└─────────────┘ └─────────────┘ └──────────────┘ └──────┬───────┘
                                                        │
                    ┌───────────────────────┐    ┌──────▼───────┐
                    │  Persistent Memory     │    │   Timeline   │
                    │  notes.md, strategy.md │    │ (append-only │
                    │  per-game + global     │    │  JSONL)      │
                    └───────────────────────┘    └──────────────┘
```

**Language: Python** (default — empty repo, no language to infer; say the word to switch to TypeScript). Python gets us Playwright, the Anthropic SDK with the beta Tool Runner (`@beta_tool`), and easy sandboxed execution of the generated `world_model.py`.

---

## 3. Components

### 3.1 Rulebook ingestion (`ingest/`)

Input: the game's rulebook PDF (downloaded from BGA's game page or the publisher).

1. **Upload once via the Files API** (beta `files-api-2025-04-14`) so the PDF is reusable across calls without re-sending base64.
2. **Structured extraction** with `client.messages.parse()` / `output_config: {format: {type: "json_schema", ...}}` into a `RulesSpec`:
   - `setup` — components, initial state, player counts
   - `turn_structure` — phases, action menu per phase, forced vs. optional actions
   - `actions` — preconditions and effects, in precise prose
   - `objective` — win/loss/scoring conditions
   - `randomness` — dice, decks, draws
   - `hidden_information` — what each player can/cannot see
   - `edge_cases` — ties, timeouts, unusual interactions the rulebook calls out
3. **Ambiguity log**: a second pass asks Claude to list every point where the rulebook underdetermines behavior. These become *hypotheses to test against BGA*, not assumptions.

Output: `games/<game>/rules_spec.json` + `games/<game>/ambiguities.md`.

### 3.2 Game model (`model/`)

The heart of the harness — Schema's editable program, adapted to turn-based games. Claude writes and iteratively repairs `games/<game>/world_model.py` exposing:

```python
def initial_state(config) -> State          # from RulesSpec.setup
def legal_actions(state, player) -> list    # action menu
def step(state, action) -> State            # transition (chance nodes explicit)
def is_terminal(state) -> bool
def score(state, player) -> float           # objective, from RulesSpec.objective
def observation(state, player) -> Obs       # hides what player can't see
```

**Certification — `run_backtest`**: replay `step()` over *every* recorded BGA transition in the Timeline. Exact match on the observable state, or a pointed counterexample (which transition, which fields mismatched). The model is only trusted for planning while the backtest is green. This is Schema's "retrodictive consistency against ground truth" — it survives context compaction because the Timeline is on disk, not in context.

**Repair discipline**: on a mismatch, Claude may revise the transition rule *or* the state representation (Schema's Level 1 vs Level 2), then re-runs the backtest. The rulebook text is evidence, but the BGA record outranks it.

Generated code runs in a **subprocess sandbox** (restricted imports, CPU/memory/time limits) — it is model-written code and gets no filesystem or network access.

### 3.3 BGA adapter (`bga/`)

Playwright-driven browser layer. Three duties:

- **Observe** (`observe_table`): capture the current table state. Primary source: BGA's structured DOM and its notification/game-log stream (BGA ships per-move notifications that are far more reliable than pixels). Secondary: a screenshot passed to Claude as a base64 image block when the DOM is ambiguous (vision fallback). Emit a normalized `Observation`.
- **Act** (`commit_actions`): translate a model-level action (e.g. `play_card(hand_idx=3)`) into UI interactions (click selectors, confirm dialogs). Per-step self-check: after each committed action, re-observe and compare against `step()`'s prediction; **any misprediction halts the plan** and returns control to deliberation with the counterexample.
- **Record**: append every `(observation, action, observation′)` transition — plus raw game-log entries — to `games/<game>/timeline.jsonl`. Append-only; nothing ever rewrites it.

A per-game **UI map** (`games/<game>/ui_map.json`) associates model actions with DOM selectors. Claude builds this map interactively the first time it plays a game (state grounding for the *interface*), and the map is then reused.

**Compliance note**: automated play may violate BGA's Terms of Use. Development happens against BGA's **solo/training modes and unrated tables**, with the account clearly used for research; do not use the harness in ranked/arena play or against non-consenting opponents. A local **offline simulator mode** (play `world_model.py` against itself) covers most development without touching BGA at all.

### 3.4 Planner (`plan/`)

Schema plans with BFS because ARC is deterministic and single-agent. Boardgames need a small portfolio, chosen from the `RulesSpec`:

- **Perfect information, deterministic** (Reversi, Nine Men's Morris): alpha-beta / iterative-deepening minimax over `step()`.
- **Chance nodes** (dice games): expectimax; chance outcomes enumerated from `RulesSpec.randomness`.
- **Hidden information** (card games): determinization + MCTS (sample opponent hands consistent with the observed history, plan against the samples).
- **Fallback**: when search is intractable, Claude evaluates candidate moves directly, using the certified model to enumerate `legal_actions` and simulate short rollouts — the model still guarantees legality and lets Claude "look ahead" cheaply.

Planning is free in real-action terms: only the chosen move is committed to BGA. (BGA's turn timers make this efficiency matter — deliberation must fit inside the clock; see §5.)

### 3.5 Agent loop (`agent/`)

Built on the **Anthropic SDK Tool Runner** (`client.beta.messages.tool_runner` with `@beta_tool` functions) — the SDK runs the request→execute→loop cycle; we supply the tools:

| Tool | Role in the Schema cycle |
|---|---|
| `observe_table()` | observe — normalized state + optional screenshot |
| `read_rules(query)` | theorize — targeted lookup in RulesSpec / rulebook |
| `write_model(patch)` | theorize — edit `world_model.py` |
| `run_backtest()` | certify — replay full Timeline, exact match or counterexample |
| `run_search(algo, budget)` | plan — search inside the certified model |
| `commit_actions(actions)` | commit — the only channel to BGA |
| `read_notes()` / `write_notes()` | persistent working memory |

API configuration (per the current Claude API surface):

- **Model**: `claude-opus-4-8` (Schema's own retained-run data: Opus 4.8 solved 13/14 of its retained games at exactly 100 RHAE). Optional escalation to `claude-fable-5` for games where Opus stalls — mirroring Schema's fixed fallback rule ("below 80 → rerun with Fable"), and its finding that Fable makes the decisive representational revision earlier.
- **Thinking**: `thinking: {type: "adaptive"}` (no `budget_tokens` — rejected on these models).
- **Streaming** always, with `.get_final_message()` when events aren't needed.
- **Prompt caching**: frozen system prompt (harness instructions + RulesSpec) marked with `cache_control: {type: "ephemeral"}`; the growing conversation rides the prefix cache. The Timeline stays on disk and is queried via tools, not stuffed into context.
- **Memory tool** (`memory_20250818`, client-side) for cross-game learning: per-game strategy files ("in Reversi, corners are worth sacrificing mobility for") and cross-game heuristics survive between sessions — the agent's "weights", exactly as Schema frames its persistent files.

### 3.6 Persistent memory (`games/<game>/`)

```
games/reversi/
  rulebook.pdf          # source document
  rules_spec.json       # structured extraction
  ambiguities.md        # rulebook underdeterminations → experiments
  world_model.py        # the executable theory (versioned by git)
  ui_map.json           # model action → DOM selector
  timeline.jsonl        # append-only ground truth
  notes.md              # working hypotheses, discarded epicycles
  strategy.md           # learned play strength (survives across matches)
```

Everything is committed to git after each session — the diff history of `world_model.py` *is* the learning curve.

---

## 4. Milestones

**Phase 0 — Scaffold (offline)**
Repo layout, sandboxed executor for generated code, Timeline format, backtest runner. Hand-write a `world_model.py` for Tic-tac-toe to validate the interfaces without any Claude calls.

**Phase 1 — Rulebook → model (offline)**
Files API upload + structured extraction → `RulesSpec` for Reversi. Claude generates `world_model.py` from the spec; certify it against a hand-scripted game transcript. Exit criterion: green backtest on a full recorded game, and the planner beats a random player >95% in self-play.

**Phase 2 — BGA adapter (one game)**
Playwright login, table creation (solo/training mode), DOM observation, game-log recording, UI-map construction, action execution with per-step prediction checks. Exit criterion: the harness plays a complete legal game of Reversi on BGA unassisted.

**Phase 3 — Full Schema loop**
Wire the deliberation cycle end to end: mispredictions void plans, counterexamples drive model repair, backtest gates planning, discriminating experiments resolve rulebook ambiguities. Exit criterion: starting from *only* the rulebook PDF, the harness reaches a green backtest within N games.

**Phase 4 — Harder games + learning**
A chance game (e.g. Can't Stop) → expectimax; a hidden-information game (e.g. Coup or Hearts) → determinized MCTS. Memory-tool strategy files; measure improvement across repeated matches. Opus→Fable escalation policy.

**Phase 5 — Generalization**
New-game onboarding as a single command (`harness learn <bga-game-id>`): fetch rulebook → extract → generate model → build UI map → play. Metrics dashboard.

---

## 5. Metrics, risks, costs

**Metrics** (Schema-inspired):
- **Backtest match rate** — fraction of recorded transitions the model reproduces exactly (Schema's 393/393-style certification)
- **Misprediction rate per game** — should collapse after model convergence (Schema's WA30: dozens → 4)
- **Action legality rate** — committed actions accepted by BGA
- **Games-to-green** — real games needed before the backtest first passes from rulebook alone
- **Win rate / Elo trend** vs BGA bots and self-play baselines

**Risks**:
- *BGA ToS / bot detection* — mitigated by solo/training-mode-only policy, offline simulator for development, and (ideally) contacting BGA for research permission before any sustained live play.
- *Turn timers* — deliberation is expensive; mitigate by planning ahead on the opponent's turn and caching the certified model's search results. Prefer "no clock" table settings.
- *DOM fragility* — BGA games each have bespoke UIs; the UI map + screenshot-vision fallback handles drift, and the per-step prediction check catches silent breakage immediately.
- *Sandbox escape of generated code* — subprocess isolation, no network, resource limits.

**Cost envelope** (Opus 4.8 at $5/$25 per MTok): a deliberation-heavy game runs on the order of a few hundred K input tokens (heavily cache-discounted) and tens of K output tokens — roughly $1–5 per game during the model-discovery phase, dropping sharply once the model is certified and moves come from search rather than long reasoning. `count_tokens` is used to enforce a per-game budget.

---

## 6. The one-sentence version

Read the rulebook into a structured spec, compile the spec into an executable `step()` program, treat every real BGA transition as ground truth that certifies or indicts that program, plan only inside a certified program, and let a single misprediction send the agent back to the theory — Schema's physicist loop, pointed at boardgames.
