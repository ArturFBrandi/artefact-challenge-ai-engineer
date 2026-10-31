"""Assemble the service from settings."""

from emporio.clock import build_clock
from emporio.config import Settings
from emporio.domain.rules import load_facts, load_rules
from emporio.ingest import ingest
from emporio.llm.factory import build_provider
from emporio.service import AgentService


def build_service(settings: Settings | None = None) -> AgentService:
    settings = settings or Settings()
    if not settings.db_path.exists():
        print(ingest(settings.db_path, settings.data_dir).render())
    return AgentService(
        settings=settings,
        provider=build_provider(settings),
        clock=build_clock(settings.store_now, settings.store_timezone),
        rules=load_rules(settings.config_dir),
        facts=load_facts(settings.config_dir),
    )
