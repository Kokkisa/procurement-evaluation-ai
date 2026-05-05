"""Settings tests, focused on the LangSmith optional-config path.

The system must run cleanly *with* LangSmith (vars present in .env) and
*without* LangSmith (vars absent / disabled), so tracing can be flipped
on and off as a deployment knob.

Also covers ``_propagate_langsmith_to_environ``: pydantic-settings only
writes to our ``Settings`` object, but LangChain's auto-tracer reads
``LANGCHAIN_*`` directly from ``os.environ`` — propagation closes the gap.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from proceval.config import Settings, _propagate_langsmith_to_environ


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


# --- LangSmith env propagation --------------------------------------------
#
# os.environ.setdefault() inside the propagation function is a direct
# mutation that monkeypatch does NOT track / revert, so each test below
# uses an explicit snapshot fixture to keep the three LANGCHAIN_* keys
# clean across tests. Without it, one test's setdefault would leak state
# into the next one's "absent" assertion.


_LS_KEYS = ("LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY", "LANGCHAIN_PROJECT")


@pytest.fixture
def _clean_langsmith_environ():
    snapshot = {k: os.environ.get(k) for k in _LS_KEYS}
    for k in _LS_KEYS:
        os.environ.pop(k, None)
    try:
        yield
    finally:
        for k, v in snapshot.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_propagation_mirrors_all_three_vars_when_tracing_enabled(_clean_langsmith_environ):
    fake = SimpleNamespace(
        langchain_tracing_v2=True,
        langchain_api_key="DUMMY_PROPAGATION_KEY",
        langchain_project="my-test-project",
    )
    _propagate_langsmith_to_environ(fake)

    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
    assert os.environ["LANGCHAIN_API_KEY"] == "DUMMY_PROPAGATION_KEY"
    assert os.environ["LANGCHAIN_PROJECT"] == "my-test-project"


def test_propagation_does_not_overwrite_shell_exported_values(_clean_langsmith_environ):
    """setdefault means a real shell-exported value wins over .env — the
    production knob: ops sets these at the container level, .env only
    primes for local dev."""
    os.environ["LANGCHAIN_TRACING_V2"] = "shell-wins"
    os.environ["LANGCHAIN_API_KEY"] = "shell-key"
    os.environ["LANGCHAIN_PROJECT"] = "shell-project"

    fake = SimpleNamespace(
        langchain_tracing_v2=True,
        langchain_api_key="env-file-key-should-lose",
        langchain_project="env-file-project-should-lose",
    )
    _propagate_langsmith_to_environ(fake)

    assert os.environ["LANGCHAIN_TRACING_V2"] == "shell-wins"
    assert os.environ["LANGCHAIN_API_KEY"] == "shell-key"
    assert os.environ["LANGCHAIN_PROJECT"] == "shell-project"


def test_propagation_no_op_when_tracing_disabled(_clean_langsmith_environ):
    """Negative path: LANGCHAIN_TRACING_V2=False (or unset) => os.environ
    is NOT touched. Even the project name (which has a non-empty default)
    must NOT leak into os.environ on the off-path."""
    fake = SimpleNamespace(
        langchain_tracing_v2=False,
        langchain_api_key="should-not-propagate",
        langchain_project="should-not-propagate",
    )
    _propagate_langsmith_to_environ(fake)

    for key in _LS_KEYS:
        assert key not in os.environ, (
            f"Off-path leaked {key!r} into os.environ — this would "
            f"silently flip LangChain's auto-tracer back on."
        )


def test_propagation_skips_empty_api_key(_clean_langsmith_environ):
    """Tracing enabled but no key => propagate the toggle + project, but
    don't push an empty LANGCHAIN_API_KEY (which would shadow a real
    shell-set key with garbage when the LangChain client comes up)."""
    fake = SimpleNamespace(
        langchain_tracing_v2=True,
        langchain_api_key="",
        langchain_project="proj",
    )
    _propagate_langsmith_to_environ(fake)

    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
    assert os.environ["LANGCHAIN_PROJECT"] == "proj"
    assert "LANGCHAIN_API_KEY" not in os.environ
