## Consecutive passes and game termination detection

**Question:** How does the engine detect that "neither player is able to make a legal move"? Does it require an explicit double-pass, and how is a pass represented in the move sequence?

**Interpretations:**
- (A) After each move, compute the mover's opponent's legal moves; if none, the opponent "passes" (possibly recorded as an explicit pass token) and control returns to the original mover. Game ends only when *both* players in succession have no move.
- (B) Game ends immediately when the current player to move has no move AND the other player also has no move — checked as a paired condition without emitting a pass token.
- (C) A pass is a recorded ply (turn counter increments) vs. a pass is invisible (no ply recorded, board state unchanged).

**Discriminating experiment:** Find recorded games that ended before square 64 was filled, or games containing a mid-game pass. Check whether transcripts include an explicit pass notation/ply and whether the move-number parity is affected. A game log where a player moves twice in a row confirms passes occur; whether a placeholder token appears distinguishes representation choices.

## Scoring: empty squares awarded to winner vs. raw disc count

**Question:** When the game ends with empty squares remaining (early termination), how is the final score computed — actual discs on board, or winner credited with all empties?

**Interpretations:**
- (A) Winner's score = winner's disc count only; empties uncounted (used to *determine* winner).
- (B) Winner's recorded score = winner's discs + all empty squares (the "tournament scoring" note), so winner always shows 64 − loser's discs.
- (C) The winner is determined by disc majority, but empties are awarded only in "tournament" recording contexts, leaving casual scoring at raw counts — engine must choose a default.

**Discriminating experiment:** Examine recorded tournament results of games that ended early (board not full). If a winner is credited with e.g. 40–24 where only 50 discs were on the board, the empties-to-winner convention is in use. Compare casual/online records that report raw counts (e.g. 33–29 summing to <64) to see divergence.

## Tie-break / draw when board not full

**Question:** When counting for a draw, do empty squares matter? Can there be a draw when empties exist but disc counts are equal?

**Interpretations:**
- (A) Draw is declared purely on equal *disc* counts, regardless of empties (e.g., 20–20 with 24 empty = draw).
- (B) Empties awarded to a "winner" logically can't apply if counts tie, so ties remain ties — but the tournament-empty rule could be read to require assignment only for a decided game.

**Discriminating experiment:** Locate an early-ending game with equal disc counts and remaining empties; check whether it is recorded as a draw or resolved some other way.

## Definition of "adjacent opposing disc" requirement in flip direction

**Question:** Must the *immediately adjacent* square in a direction hold an opposing disc, or could a bracket start after a gap? (Text says "an unbroken row bordered at each end" — but relies on the reader inferring adjacency.)

**Interpretations:**
- (A) Standard: the square directly next to the placed disc must be opponent-colored; any empty or own-color adjacent disc voids that direction.
- (B) A looser reading where "bordered at each end" is satisfied by any bracketing without adjacency (nonstandard, essentially impossible but the text technically only defines by outflank description).

**Discriminating experiment:** Any real game move where a placement is adjacent to an empty square in a given direction and no flip occurs there confirms adjacency requirement (A). Universally observed.

## "In passing" flips — precise ordering/simultaneity semantics

**Question:** The rule forbids flipping discs bracketed only "as a side effect of flips elsewhere." How is this operationalized — which discs count as bracketed *by the move* vs. *by resulting flips*?

**Interpretations:**
- (A) Only discs lying on one of the eight straight rays from the placed square, bracketed by an unbroken opponent run ending in the player's own disc *as it existed before the move*, are flipped. All other reconfigurations are ignored. (Standard.)
- (B) An iterative/cascading interpretation where newly flipped discs could create new brackets that also flip (explicitly forbidden by the text, but a naive implementer might do it).
- (C) Ambiguity about whether a same-colored disc that becomes same-colored *because it was just flipped* can serve as the closing bracket for another ray in the same move.

**Discriminating experiment:** Construct/find a position where placing a disc flips a row that, post-flip, would newly bracket a perpendicular row. Standard engines flip only the directly-ray-bracketed discs. Compare against any recorded game move's resulting board to confirm no cascades occur.

## Simultaneous multi-direction flips — atomicity

**Question:** When a move brackets rows in multiple directions, are they evaluated all against the pre-move board simultaneously, or sequentially (where earlier flips affect later direction evaluation)?

**Interpretations:**
- (A) All eight directions evaluated against the original board state; union of bracketed discs flipped atomically.
- (B) Directions processed in some order, each seeing the results of prior flips (could change outcomes at intersections — though intersections only occur at the placed square, so likely equivalent).

**Discriminating experiment:** These are provably equivalent because rays only share the placed square; but verify by finding any move flipping in ≥3 directions and confirming the recorded flip set equals the pre-move union. No real divergence expected, but confirms implementation choice is moot.

## Column/row labelling orientation

**Question:** Rows are "1 to 8 from top to bottom" and columns "a to h left to right" — but "top" from whose perspective (Black's side)? The setup coordinates (d4/e5 white, e4/d5 black) fix orientation only if labelling is consistent.

**Interpretations:**
- (A) Fixed absolute board coordinates independent of player seating; a1 top-left as printed.
- (B) Board could be viewed from either player's side, flipping coordinate meaning — but the fixed setup squares disambiguate the intended standard.

**Discriminating experiment:** Check recorded transcripts: standard Othello notation has Black's typical opening at squares like f5/d3/c4/e6. Verify recorded first moves match the a1-top-left convention with the given initial four discs.

## First-move symmetry / which legal moves Black has

**Question:** Not an ambiguity in rules per se, but the engine must derive that Black has exactly four opening moves. Is there any provision that the standard diagonal setup is fixed, or could the "Black on e4/d5" be swapped?

**Interpretations:**
- (A) Setup exactly as stated (White d4/e5, Black e4/d5) — fixed diagonal.
- (B) The alternative diagonal orientation (some rule variants let players choose) — not permitted here.

**Discriminating experiment:** All recorded games should start from the single stated configuration; observe that Black's four legal first moves are d3, c4, f5, e6 (given the stated setup). A deviation would indicate a different setup convention.

## Whether a player who reaches zero discs mid-game ends the game

**Question:** A note says a player can end with zero discs. But if a player is reduced to zero discs mid-game, can the game continue (the zero-disc player may still move if a placement flips), or does zero discs trigger immediate loss?

**Interpretations:**
- (A) Zero discs is not a terminal condition; play continues until no legal moves exist for either side. A wiped-out player may re-enter by placing a disc that flips.
- (B) Some variants treat total elimination as immediate game over. The rulebook implies (A) via "end with zero discs... that player loses" (i.e., game reached its natural end with them at zero).

**Discriminating experiment:** Find a recorded game where one color's disc count momentarily hits zero but the game continues. If such games exist and continue, (A) holds.

## Turn passing back after a forced pass — does the passing player get re-checked?

**Question:** After player X moves and opponent Y must pass, X moves again. After X's second move, is Y re-checked for legal moves (normal flow) — and can a single player make an unbounded run of consecutive moves while the opponent keeps passing?

**Interpretations:**
- (A) Yes — repeated passes are allowed; one player may make many consecutive moves as long as the other has none each time.
- (B) A cap or alternation-forcing rule (not stated) — unlikely but a naive implementer might mishandle repeated passes.

**Discriminating experiment:** Find recorded endgames where one player makes 2+ consecutive moves due to repeated opponent passes. Their existence confirms (A).

## Legality when placing on the last empty square that flips nothing

**Question:** At game's near-end, if the only empty squares available flip nothing for the player to move, must they pass even though empties remain? (Interaction of "can't pass voluntarily" with "must flip ≥1".)

**Interpretations:**
- (A) Player passes; empties remain; if opponent also can't flip, game ends with empty squares on board.
- (B) Some implementations force-fill remaining squares — not supported by text.

**Discriminating experiment:** Locate recorded games ending with empty squares still on the board (sum of black+white < 64). Confirms passing-with-empties (A).

## Representation of the disc-count majority when total discs is fixed

**Question:** Since flipped discs never leave the board and every placement adds one disc, is winner always simply "more than 32," or must ties/empties be handled? (Determines default comparison logic.)

**Interpretations:**
- (A) Compare black count vs white count directly; majority wins, equal = draw — independent of empties.
- (B) Compare against 32 threshold (valid only when board full).

**Discriminating experiment:** Use an early-ended game (empties present): if the side with fewer than 32 discs but more than the opponent is declared winner, (A) is correct; a threshold-of-32 implementation would misjudge it.
