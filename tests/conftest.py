import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from fixtures.layer import FixtureDataLayer


@pytest.fixture
def layer():
    return FixtureDataLayer()
