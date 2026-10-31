from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from emporio.clock import FrozenClock
from emporio.config import ROOT
from emporio.domain.rules import PolicyRules, StoreFacts, load_facts, load_rules


@pytest.fixture(scope="session")
def rules() -> PolicyRules:
    return load_rules(ROOT / "config")


@pytest.fixture(scope="session")
def facts() -> StoreFacts:
    return load_facts(ROOT / "config")


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(datetime.fromisoformat("2026-03-25T10:00:00-04:00"))


@pytest.fixture
def tmp_db(tmp_path: Path) -> Iterator[Path]:
    yield tmp_path / "emporio.db"
