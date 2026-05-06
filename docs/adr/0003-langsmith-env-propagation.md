# ADR 0003: Propagate LangSmith Env Vars to `os.environ`

- **Status:** Accepted
- **Date:** Block 10 (LangSmith trace debugging)
- **Decision-maker:** Project lead

## Context

LangSmith integration was wired in Block 9 by setting three values in `.env`:

```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=procurement-evaluation-ai
```

The expectation: every `chain.ainvoke()` from the agents would automatically emit a trace to LangSmith, populating the dashboard with parent + child runs, token counts, and latency.

The reality during Block 10 testing: **zero traces appeared**, despite all three values loading correctly into the `Settings` object.

A diagnostic script (`scripts/diagnose_langsmith.py`) constructed a `langsmith.RunTree` directly and POSTed a synthetic trace. That **succeeded** -- the trace appeared in the dashboard within seconds. So credentials, network, project routing, and workspace permissions were all fine.

The asymmetry: **manual scripts produced traces, agent runs did not**.

## Investigation

Initial hypothesis (incorrect): "The agents bypass LangChain and call the OpenAI/Anthropic SDKs directly, so LangChain's auto-tracer never sees them."

Verification step:
```bash
$ grep -rn "from openai import\|from anthropic import" src/
# No matches.
```

The agents used LangChain wrappers throughout (per ADR-0001). The hypothesis was wrong.

Second hypothesis (correct): "The env vars are loaded into `Settings` but not exported back to `os.environ`."

Verification:
```bash
$ env | grep '^LANGCHAIN_'
# Empty -- nothing in the process environment.
```

But:
```python
>>> from proceval.config import settings
>>> settings.langchain_tracing_v2
True
>>> settings.langchain_api_key
'lsv2_pt_...'
```

The values were in the `Settings` object but not in `os.environ`.

**Root cause:** `pydantic-settings` reads `.env` and populates the `Settings` instance. It does **not** export those values back to the process environment. LangChain's auto-tracer reads `os.environ['LANGCHAIN_TRACING_V2']` etc. directly -- it has no awareness of our `Settings` object.

This explained the asymmetry perfectly:

| Tracing surface | Sees env vars? |
|---|---|
| Manual diagnostic script (calls `load_dotenv()` explicitly) | Yes |
| Agent runs through FastAPI / `run_eval_test.py` (only `Settings()`) | No |

## Decision

**Add a `_propagate_langsmith_to_environ()` helper in `src/proceval/config.py` that mirrors the three LangSmith fields back to `os.environ` after `Settings()` is constructed.**

```python
def _propagate_langsmith_to_environ(settings: Settings) -> None:
    """Mirror LangSmith config to os.environ so LangChain's auto-tracer can read it."""
    if not settings.langchain_tracing_v2:
        return
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    if settings.langchain_api_key:
        os.environ.setdefault("LANGCHAIN_API_KEY", settings.langchain_api_key)
    os.environ.setdefault("LANGCHAIN_PROJECT", settings.langchain_project)


settings = Settings()
_propagate_langsmith_to_environ(settings)
```

Two implementation details matter:

- **`os.environ.setdefault`, not direct assignment.** A real shell-exported value still wins over the `.env` value. This matters in production where ops sets env vars at the container level and expects them to take precedence over committed defaults.
- **No-op when tracing is disabled.** If `LANGCHAIN_TRACING_V2=false`, the function returns early without touching `os.environ`. Test environments and CI runs that disable tracing don't pay any propagation cost.

## Consequences

### Positive

- **Auto-tracing works.** Two successful E2E runs after the fix produced 305 traces in LangSmith with no agent code changes. Token counts, P50/P99 latencies, and per-criterion trace details all populated automatically.
- **Pattern is reusable.** Any future config that bridges `pydantic-settings` and a third-party library that reads `os.environ` can use the same propagation helper. Documented as the project default.
- **`setdefault` semantics are production-correct.** Container-level env vars override `.env` defaults, which matches 12-factor expectations.

### Negative

- **Side effect at module import time.** Modifying `os.environ` during import is generally an anti-pattern -- it's hard to test in isolation and surprises new contributors. Mitigated by:
  - A prominent comment in `config.py` explaining why this is necessary.
  - Test-environment overrides in `tests/conftest.py` that force `LANGCHAIN_TRACING_V2=false` before the propagation runs.
  - Four dedicated tests in `tests/test_config.py` covering: mirrors-when-enabled, shell-wins-via-setdefault, no-op-when-disabled, skips-empty-API-key.
- **Test suite slowdown surfaced and was fixed.** When propagation went live, mocked tests that touched LangChain Runnables tried to POST traces over the network and inherited the production `LLM_INTER_BATCH_SLEEP_SECONDS=10`, ballooning the suite from 6s to 100s+. Fixed via `tests/conftest.py` forcing `LANGCHAIN_TRACING_V2=false` and `LLM_INTER_BATCH_SLEEP_SECONDS=0` for the test session. See [ADR-0002](0002-bounded-concurrency-orchestration.md).

## Alternatives Considered

- **Migrate agents to use raw OpenAI/Anthropic SDKs and roll our own tracing.** Estimated 2-3 weeks of work to match LangChain's automatic instrumentation depth (parent runs, child spans, token accounting, retries, structured output capture). Rejected as undifferentiated heavy lifting -- and orthogonal to the actual problem.
- **Call `load_dotenv()` at the top of every entrypoint.** Works for scripts but doesn't help when FastAPI imports `Settings()` and never calls `load_dotenv()` explicitly. Rejected as fragile -- depends on remembering to add the call to every new entry point.
- **Patch LangChain to read from a settings object.** Upstream change, would diverge from official releases. Rejected.
- **Set the env vars in a process wrapper (Docker, systemd, etc.).** Production-correct but doesn't help during local development where `.env` is the source of truth. Would force two parallel config mechanisms. Rejected.

## Validation

- Diagnostic test trace via `scripts/diagnose_langsmith.py` -- confirmed the LangSmith pipe was always working.
- After the fix: 305 traces from two E2E runs visible in the `procurement-evaluation-ai` project on LangSmith dashboard.
- Aggregate stats observed: 680K tokens, $0.11 total cost, P50 latency 1.62s, P99 5.39s, 7% error rate (within expected drift for a system tuned for Claude running on gpt-4o-mini).
- Four propagation tests in `tests/test_config.py` pass; full suite is 149 passing, 13 gated.

## Related

- [ADR-0001](0001-provider-agnostic-llm-factory.md) -- The LangChain factory whose auto-tracing this fix unblocks.
- [ADR-0002](0002-bounded-concurrency-orchestration.md) -- The throttle whose test-environment override was prompted by this fix's side effect.

## Lesson banked

When an LLM (or anyone) gives a confident diagnosis of an unfamiliar codebase, **grep before refactoring**. The first hypothesis here ("agents bypass LangChain") was wrong, and acting on it would have wasted 30-60 minutes on a refactor that didn't address the actual root cause. The five-line `grep` check rejected the hypothesis cleanly. This is now a workflow default for the project: any diagnosis that proposes a refactor must include a grep or AST-level verification step before code changes begin.
