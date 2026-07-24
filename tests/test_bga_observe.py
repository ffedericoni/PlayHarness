import pytest

from playharness.bga.observe import (
    ObservationError,
    normalize,
    normalize_reversi,
    reversi_action_ui_vars,
)


def make_raw(board_cells, active="101", gamestate="playerTurn", viewer="101"):
    return {
        "game_name": "reversi",
        "player_id": viewer,
        "table_id": "555",
        "active_player": active,
        "gamestate_name": gamestate,
        "gamedatas": {
            "players": {
                "101": {"color": "000000", "score": "2"},
                "202": {"color": "ffffff", "score": "2"},
            },
            "board": board_cells,
        },
        "logs": ["Alice plays d3"],
    }


# BGA serves x = column 1..8, y = row 1..8 from the top; flat index = (y-1)*8+(x-1).
INITIAL_CELLS = [
    {"x": "4", "y": "4", "player": "202"},  # d4 White -> 27
    {"x": "5", "y": "4", "player": "101"},  # e4 Black -> 28
    {"x": "4", "y": "5", "player": "101"},  # d5 Black -> 35
    {"x": "5", "y": "5", "player": "202"},  # e5 White -> 36
    {"x": "1", "y": "1", "player": None},
]


def test_normalize_initial_position_matches_world_model(reversi):
    obs = normalize_reversi(make_raw(INITIAL_CELLS))
    initial = reversi.initial_state({})
    assert obs["board"] == initial["board"]
    assert obs["to_move"] == 0
    assert obs["viewer_player"] == 0
    assert obs["game_over"] is False
    assert obs["scores_raw"] == {"0": 2, "1": 2}
    assert obs["logs"] == ["Alice plays d3"]


def test_normalize_board_as_dict():
    cells = {f"{c['x']}_{c['y']}": c for c in INITIAL_CELLS}
    obs = normalize_reversi(make_raw(cells))
    assert sum(v is not None for v in obs["board"]) == 4


def test_game_end_state_carries_final_scores():
    obs = normalize_reversi(make_raw(INITIAL_CELLS, gamestate="gameEnd"))
    assert obs["game_over"] is True
    assert obs["to_move"] is None
    assert obs["final_scores"] == {"0": 0.0, "1": 0.0}  # 2 discs each


def test_white_viewer():
    obs = normalize_reversi(make_raw(INITIAL_CELLS, active="202", viewer="202"))
    assert obs["viewer_player"] == 1
    assert obs["to_move"] == 1


def test_unknown_disc_owner_raises():
    bad = [{"x": 1, "y": 1, "player": "999"}]
    with pytest.raises(ObservationError):
        normalize_reversi(make_raw(bad))


def test_registry_dispatch():
    assert normalize("reversi", make_raw(INITIAL_CELLS))["game"] == "reversi"
    with pytest.raises(ObservationError):
        normalize("chess", {})


def test_action_ui_vars_expand_cell_to_bga_coordinates():
    # cell 44 = row 5, col 4 -> BGA square x=5, y=6
    assert reversi_action_ui_vars({"type": "place", "cell": 44}) == {"x": 5, "y": 6}
    assert reversi_action_ui_vars({"type": "pass"}) == {}
