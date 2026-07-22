"""Offline tests for table lifecycle helpers, using a fake page that emulates
BGA's request-token endpoints."""

import json

import pytest

from playharness.bga import table as table_mod
from playharness.bga.table import TableError


class FakeBGAPage:
    """Emulates page.evaluate for the in-page fetch used by call_bga."""

    def __init__(self, responses: dict[str, dict], token="tok123"):
        self.responses = responses  # path -> JSON dict BGA would return
        self.token = token
        self.calls: list[tuple[str, dict]] = []

    def evaluate(self, js, arg=None):
        # call_bga passes {"path":..., "params":...}; token lookup is inlined in JS
        if isinstance(arg, dict) and "path" in arg:
            path = arg["path"]
            self.calls.append((path, arg["params"]))
            body = self.responses.get(path)
            if body is None:
                return {"status": 404, "body": "not found"}
            return {"status": 200, "body": json.dumps(body)}
        return None


def test_table_url_accepts_id_or_url():
    assert table_mod.table_url("https://x.bga.com", "42") == "https://x.bga.com/table?table=42"
    assert table_mod.table_url("https://x.bga.com", "https://x/table?table=9") == "https://x/table?table=9"


def test_create_table_returns_id():
    page = FakeBGAPage({"/table/table/createnew.html": {"status": 1, "data": {"table": 887081587}}})
    table_id = table_mod.create_table(page, "reversi", mode="async", force_manual=True)
    assert table_id == "887081587"
    path, params = page.calls[0]
    assert path == "/table/table/createnew.html"
    assert params["game"] == "35"  # reversi's BGA id
    assert params["gamemode"] == "async"
    assert params["forceManual"] == "true"


def test_create_table_unknown_game():
    page = FakeBGAPage({})
    with pytest.raises(TableError, match="no BGA game id"):
        table_mod.create_table(page, "chess")


def test_create_table_surfaces_bga_error():
    page = FakeBGAPage({"/table/table/createnew.html": {
        "status": 0, "error": "Invalid session information", "code": 806}})
    with pytest.raises(TableError, match="Invalid session information"):
        table_mod.create_table(page, "reversi")


def test_cancel_and_start_hit_right_endpoints():
    page = FakeBGAPage({
        "/table/table/quitgame.html": {"status": 1, "data": "ok"},
        "/table/table/startgame.html": {"status": 1, "data": "ok"},
    })
    table_mod.cancel_table(page, "42")
    table_mod.start_table(page, "42")
    paths = [c[0] for c in page.calls]
    assert paths == ["/table/table/quitgame.html", "/table/table/startgame.html"]
    assert all(c[1]["table"] == "42" for c in page.calls)


def test_call_bga_non_json_raises():
    page = FakeBGAPage({})  # unknown path -> {"status":404,"body":"not found"}
    with pytest.raises(TableError, match="non-JSON"):
        table_mod.call_bga(page, "/table/table/createnew.html")
