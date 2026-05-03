"""Settings tests, focused on the LangSmith optional-config path.

The system must run cleanly *with* LangSmith (vars present in .env) and
*without* LangSmith (vars absent / disabled), so tracing can be flipped
on and off as a deployment knob.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from proceval.config import Settings


@pytest.fixture
def _isolated_env(monkeypatch):
    """Clear all overridable env vars so .env values aren't shadowed."""
    for var in (
        "LANGCHAIN_TRACING_V2",
        "LANGCHAIN_API_KEY",
        "LANGCHAIN_PROJECT",
        "ANTHROPIC_API_KEY",
        "DATABASE_URL",
        "LLM_MAX_CONCURRENCY",
        "LLM_INTER_BATCH_SLEEP_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)


def test_loads_langsmith_vars_when_present_in_env_file(_isolated_env, tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LANGCHAIN_TRACING_V2=true\n"
        "LANGCHAIN_API_KEY=DUMMY_LANGSMITH_TOKEN_VALUE\n"
        "LANGCHAIN_PROJECT=my-test-project\n"
    )

    s = Settings(_env_file=str(env_file))

    assert s.langchain_tracing_v2 is True
    assert s.langchain_api_key == "DUMMY_LANGSMITH_TOKEN_VALUE"
    assert s.langchain_project == "my-test-project"


def test_langsmith_optional_when_absent(_isolated_env, tmp_path: Path):
    """When the .env doesn't mention LangSmith at all, defaults must hold and
    Pydantic must NOT raise (the fields are optional)."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        # No LangSmith vars at all
        "ANTHROPIC_API_KEY=DUMMY_ANTHROPIC_KEY_VALUE\n"
    )

    s = Settings(_env_file=str(env_file))

    assert s.langchain_tracing_v2 is False
    assert s.langchain_api_key == ""
    assert s.langchain_project == "procurement-evaluation-ai"


def test_langsmith_explicit_false(_isolated_env, tmp_path: Path):
    """LANGCHAIN_TRACING_V2=false must be honored — common production toggle."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LANGCHAIN_TRACING_V2=false\n"
        "LANGCHAIN_API_KEY=DUMMY_INERT_TOKEN\n"
        "LANGCHAIN_PROJECT=ignored-when-disabled\n"
    )

    s = Settings(_env_file=str(env_file))

    assert s.langchain_tracing_v2 is False
    # Key is still loaded — the user is responsible for keeping it valid;
    # only the tracing toggle controls whether it's used.
    assert s.langchain_api_key == "DUMMY_INERT_TOKEN"
    assert s.langchain_project == "ignored-when-disabled"


# --- LLM rate-limit knobs --------------------------------------------------


def test_llm_throttle_defaults_when_absent(_isolated_env, tmp_path: Path):
    """No values in .env => Tier-1 safe defaults: cap 3, 1.5s inter-batch."""
    env_file = tmp_path / ".env"
    env_file.write_text("")

    s = Settings(_env_file=str(env_file))

    assert s.llm_max_concurrency == 3
    assert s.llm_inter_batch_sleep_seconds == 1.5


def test_llm_throttle_overridable_via_env_file(_isolated_env, tmp_path: Path):
    """A higher tier can raise the cap and lower the sleep without code changes."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_MAX_CONCURRENCY=8\n"
        "LLM_INTER_BATCH_SLEEP_SECONDS=0.25\n"
    )

    s = Settings(_env_file=str(env_file))

    assert s.llm_max_concurrency == 8
    assert s.llm_inter_batch_sleep_seconds == 0.25
