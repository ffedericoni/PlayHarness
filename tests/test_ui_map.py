import pytest

from playharness.bga.ui_map import UIMap, UIMapError
from playharness.model_api import games_dir


def test_selector_formatting():
    ui_map = UIMap.load(games_dir() / "reversi" / "ui_map.json")
    selector, method = ui_map.selector_for({"type": "play_disc", "x": 4, "y": 3})
    assert selector == "#square_4_3"
    assert method == "click"


def test_unmapped_action_raises():
    ui_map = UIMap({"game": "reversi", "actions": {}})
    with pytest.raises(UIMapError):
        ui_map.selector_for({"type": "teleport"})


def test_missing_field_raises():
    ui_map = UIMap({"game": "g", "actions": {"mv": {"selector": "#a_{x}"}}})
    with pytest.raises(UIMapError):
        ui_map.selector_for({"type": "mv"})


def test_save_round_trip(tmp_path):
    ui_map = UIMap({"game": "g", "actions": {"mv": {"selector": "#a_{x}", "method": "click"}}})
    path = tmp_path / "ui_map.json"
    ui_map.save(path)
    loaded = UIMap.load(path)
    assert loaded.selector_for({"type": "mv", "x": 9}) == ("#a_9", "click")
