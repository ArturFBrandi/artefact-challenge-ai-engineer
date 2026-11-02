import shutil
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from emporio.clock import Clock, FrozenClock
from emporio.config import ROOT, Settings
from emporio.domain.rules import PolicyRules, StoreFacts, load_facts, load_rules
from emporio.llm.fake import FakeLLMProvider
from emporio.service import AgentService


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


@pytest.fixture(scope="session")
def seeded_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from emporio.ingest import ingest

    path = tmp_path_factory.mktemp("seed") / "emporio.db"
    ingest(path, ROOT / "data")
    return path


@pytest.fixture
def db_path(seeded_db: Path, tmp_path: Path) -> Path:
    """A private copy per test, so writes never leak between tests."""
    copy = tmp_path / "emporio.db"
    shutil.copy(seeded_db, copy)
    return copy


@pytest.fixture
def settings(db_path: Path, tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        llm_provider="fake",
        db_path=db_path,
        trace_dir=tmp_path / "traces",
        max_tool_rounds=4,
    )


@pytest.fixture
def make_service(settings, clock, rules, facts):
    def build(
        script=(), at: Clock | None = None, **overrides
    ) -> tuple[AgentService, FakeLLMProvider]:
        provider = FakeLLMProvider(script)
        configured = settings.model_copy(update=overrides)
        service = AgentService(configured, provider, at or clock, rules, facts)
        return service, provider

    return build
