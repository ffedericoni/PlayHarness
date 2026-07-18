import pytest

from playharness.bga.observe import ObservationError, normalize, normalize_reversi


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
        "logs": ["move 1: Alice plays E6"],
    }


INITIAL_CELLS = [
    {"x": "4", "y": "4", "player": "202"},
    {"x": "5", "y": "5", "player": "202"},
    {"x": "5", "y": "4", "player": "101"},
    {"x": "4", "y": "5", "player": "101"},
    {"x": "1", "y": "1", "player": None},
]


def test_normalize_initial_position():
    obs = normalize_reversi(make_raw(INITIAL_CELLS))
    assert obs["game"] == "reversi"
    assert obs["board"][3][3] == 2 and obs["board"][4][4] == 2
    assert obs["board"][3][4] == 1 and obs["board"][4][3] == 1
    assert sum(c != 0 for row in obs["board"] for c in row) == 4
    assert obs["to_move"] == "black"
    assert obs["viewer_color"] == "black"
    assert obs["game_over"] is False
    assert obs["scores"] == {"black": 2, "white": 2}
    assert obs["logs"] == ["move 1: Alice plays E6"]


def test_normalize_board_as_dict():
    cells = {f"{c['x']}_{c['y']}": c for c in INITIAL_CELLS}
    obs = normalize_reversi(make_raw(cells))
    assert sum(c != 0 for row in obs["board"] for c in row) == 4


def test_game_end_state():
    obs = normalize_reversi(make_raw(INITIAL_CELLS, gamestate="gameEnd"))
    assert obs["game_over"] is True
    assert obs["to_move"] is None


def test_white_viewer():
    obs = normalize_reversi(make_raw(INITIAL_CELLS, active="202", viewer="202"))
    assert obs["viewer_color"] == "white"
    assert obs["to_move"] == "white"


def test_unknown_disc_owner_raises():
    bad = [{"x": 1, "y": 1, "player": "999"}]
    with pytest.raises(ObservationError):
        normalize_reversi(make_raw(bad))


def test_registry_dispatch():
    assert normalize("reversi", make_raw(INITIAL_CELLS))["game"] == "reversi"
    with pytest.raises(ObservationError):
        normalize("chess", {})
