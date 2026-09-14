import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from autodraft.masters import MasterData  # noqa: E402
from tools.make_synthetic_docs import BUILDERS  # noqa: E402


@pytest.fixture(scope="session")
def documents(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The synthetic corpus, built once per test session."""
    directory = tmp_path_factory.mktemp("documents")
    for name, builder in BUILDERS.items():
        builder(directory / name)
    return directory


@pytest.fixture(scope="session")
def masters() -> MasterData:
    return MasterData(ROOT / "master_data")


@pytest.fixture(scope="session")
def cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("cache")
