"""Gated end-to-end runner test.

Imports scripts/run_eval_test.py as a module and calls its main(). Skipped
unless RUN_LIVE_LLM_TESTS=1 (same gate as the other live-LLM tests in
the suite). When run, it makes real LLM calls — budget ~$0.50/run on
claude-sonnet-4-5.

If the gate is set but the API key is missing, the test still skips
with a clear reason rather than failing.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = REPO_ROOT / "scripts" / "run_eval_test.py"

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LLM_TESTS") != "1",
    reason="Set RUN_LIVE_LLM_TESTS=1 to run real-LLM E2E test (~$0.50)",
)


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("run_eval_test", RUNNER_PATH)
    if spec is None or spec.loader is None:
        pytest.skip(f"Could not load runner module from {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_eval_test"] = module
    spec.loader.exec_module(module)
    return module


def test_run_eval_test_main_returns_gold_standard_split():
    from proceval.config import settings

    if not settings.anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY not set; cannot run live E2E")

    runner = _load_runner_module()
    result = runner.main()

    # Sanity assertions on the returned summary
    assert result["iteration"] == 1
    assert result["audit_event_count"] >= 5  # uploaded, metadata_*, eval_generated, sent_for_review
    assert Path(result["pdf_path"]).exists()

    # Gold-standard split — the same invariant the script asserts inline,
    # re-asserted here so pytest reports a clean failure rather than sys.exit(1).
    assert result["verdicts"] == runner.EXPECTED_VERDICTS, (
        f"Verdict mismatch.\n"
        f"  expected: {runner.EXPECTED_VERDICTS}\n"
        f"  actual:   {result['verdicts']}"
    )
