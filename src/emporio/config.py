"""Typed settings, loaded from the environment and .env."""

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    app_env: Literal["development", "test"] = "development"

    llm_provider: Literal["minimax", "fake"] = "minimax"
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "https://api.minimax.io/v1"
    llm_model: str = "MiniMax-M3"
    llm_timeout_seconds: float = 60
    llm_max_retries: int = 2
    llm_max_completion_tokens: int = 4096
    llm_thinking: Literal["adaptive", "disabled"] = "adaptive"
    llm_price_input_per_mtok: float = 0.30
    llm_price_output_per_mtok: float = 1.20

    max_tool_rounds: int = 6
    memory_window_turns: int = 12
    verification_ttl_minutes: int = 30

    db_path: Path = ROOT / "var" / "emporio.db"
    trace_dir: Path = ROOT / "var" / "traces"
    data_dir: Path = ROOT / "data"
    config_dir: Path = ROOT / "config"

    store_timezone: str = "America/Campo_Grande"
    store_now: datetime | None = None

    web_host: str = "127.0.0.1"
    web_port: int = 8000
    log_level: str = "INFO"

    @field_validator("store_now", mode="before")
    @classmethod
    def _blank_clock_means_real_time(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("store_now")
    @classmethod
    def _frozen_clock_needs_offset(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("STORE_NOW needs a UTC offset, e.g. 2026-03-25T10:00:00-04:00")
        return value
