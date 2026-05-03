"""Application settings loaded from environment / .env file."""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # Empty env vars shadow .env values by default; ignore them so an
        # inherited empty ANTHROPIC_API_KEY=  doesn't mask the real value
        # the user wrote into .env.
        env_ignore_empty=True,
    )

    # Default to Anthropic; switch with LLM_PROVIDER env var.
    llm_provider: Literal["anthropic", "openai", "ollama"] = "anthropic"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    ollama_model: str = "llama3.1"
    ollama_base_url: str = "http://localhost:11434"

    database_url: str = "postgresql+psycopg://proceval:proceval@localhost:5432/proceval"

    # LLM orchestration throttling. Anthropic Tier 1 caps input at
    # 30k tokens/min; per-(vendor, criterion) calls run ~5k input each, so
    # a hard concurrency cap + small inter-batch margin keeps us off the
    # 429 path. Tunable via .env without code changes.
    llm_max_concurrency: int = 3
    llm_inter_batch_sleep_seconds: float = 1.5

    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "procurement-evaluation-ai"

    upload_dir: Path = Field(default=Path("./data/uploads"))
    output_dir: Path = Field(default=Path("./data/outputs"))
    log_level: str = "INFO"


settings = Settings()
