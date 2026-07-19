import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from playharness.model_api import load_model  # noqa: E402

TICTACTOE_PATH = REPO_ROOT / "games" / "tictactoe" / "world_model.py"
REVERSI_REFERENCE_PATH = REPO_ROOT / "games" / "reversi" / "reference_model.py"


@pytest.fixture(scope="session")
def tictactoe():
    return load_model(str(TICTACTOE_PATH), module_name="tictactoe_world_model")


@pytest.fixture()
def tictactoe_path():
    return TICTACTOE_PATH


@pytest.fixture(scope="session")
def reversi():
    return load_model(str(REVERSI_REFERENCE_PATH), module_name="reversi_reference_model")
