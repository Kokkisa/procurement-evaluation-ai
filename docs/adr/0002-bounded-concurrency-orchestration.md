# ADR 0002: Bounded Concurrency for LLM Orchestration

- **Status:** Accepted
- **Date:** Block 10 (rate-limit incident response)
- **Decision-maker:** Project lead

## Context

The evaluation pipeline fans out aggressively. For a 5-vendor tender with ~16 criteria each (split into technical and commercial), a single end-to-end run produces approximately:

- 5 vendors x ~16 criteria = ~80 LLM calls
- Each call: ~3-5K input tokens, ~500-1K output tokens
- Naive parallelism: peak ~135K input tokens/min observed in early Block 10 testing

Anthropic Tier 1 rate limit is **30K input TPM**. OpenAI Tier 1 is **200K input TPM**. Both are rolling-window limits, not per-second. The peak above tripped Anthropic's Tier 1 ceiling repeatedly during Block 10's first four E2E attempts.

We needed a concurrency control pattern with three properties:

1. **Survive the 30K TPM ceiling** without per-call retries that mask the underlying problem.
2. **Not slow tests** that mock the LLM and don't care about throttling.
3. **Survive provider swaps** -- the orchestration layer should not assume which provider is underneath.

## Decision

**Adopt a single global semaphore plus a configurable inter-batch sleep, both wrapped around the LLM call site rather than the agent.**

Two configuration knobs:

| Knob | Default | Purpose |
|---|---|---|
| `LLM_MAX_CONCURRENCY` | 3 | Max parallel in-flight LLM calls |
| `LLM_INTER_BATCH_SLEEP_SECONDS` | 1.5 | Sleep between batch transitions |

Implementation pattern:

```python
_llm_semaphore = asyncio.Semaphore(settings.llm_max_concurrency)

async def _bounded_llm_call(chain, inputs, *, vendor, criterion):
    async with _llm_semaphore:
        log.info(f"Acquired LLM slot for {vendor} / {criterion}")
        result = await chain.ainvoke(inputs)
        log.info(f"Sleeping {settings.llm_inter_batch_sleep_seconds}s before batch N (token-bucket margin)")
        await asyncio.sleep(settings.llm_inter_batch_sleep_seconds)
    return result
```

Critical implementation details:

- **The semaphore is module-level**, not per-agent. Both technical and commercial evaluation agents share it. Without this, parallel agent execution doubles the effective concurrency and defeats the cap.
- **Sleep is inside the semaphore-held block**, so the slot stays held during the sleep. Without this, a freed slot is immediately re-acquired and the rolling window stays saturated.
- **Production tuning lives in `.env`.** The deployed configuration uses `LLM_MAX_CONCURRENCY=1` and `LLM_INTER_BATCH_SLEEP_SECONDS=10` for maximum Tier 1 safety on Anthropic. OpenAI deployments can ratchet these down.
- **Test environment overrides at conftest level.** `tests/conftest.py` forces `LLM_INTER_BATCH_SLEEP_SECONDS=0` regardless of `.env`, so the test suite stays under 10 seconds end-to-end. See "Consequences" below.

## Consequences

### Positive

- **End-to-end runs survive Anthropic Tier 1 with margin.** Math at production tuning (cap=1, sleep=10s): 80 calls x ~6.5s per slot = ~520s wall time, peak input TPM around ~25K (under 30K ceiling). Verified across two successful E2E runs.
- **Provider swap does not require re-tuning.** The semaphore is provider-agnostic. Switching to OpenAI Tier 1 (200K TPM) just means we could safely run faster -- but the same configuration runs without issue.
- **Diagnosable.** Each slot acquisition logs the vendor / criterion. A stuck batch is visually obvious in the log stream. Combined with LangSmith trace timestamps, we can attribute latency to any specific criterion.
- **Single point of control.** All future rate-limit work (token-bucket, adaptive throttle, per-provider tiers) plugs in at this one site. No agent code changes needed.

### Negative

- **Wall-clock latency is high under tight tuning.** A 5-vendor evaluation at cap=1, sleep=10s takes ~5 minutes. This is acceptable for a procurement workflow (humans review the output anyway) but would be unacceptable for interactive use. Loosen the knobs for higher tiers.
- **Test environment side effect (resolved, but worth noting).** When LangSmith env propagation was added in [ADR-0003](0003-langsmith-env-propagation.md), test inheritance of the production `LLM_INTER_BATCH_SLEEP_SECONDS=10` value caused the test suite to balloon from ~6s to ~100s. Fixed by adding test-environment overrides in `tests/conftest.py`. The lesson: production tuning and test runtime characteristics must be decoupled at the conftest layer.
- **Static knobs, not adaptive.** A surge of provider-side congestion that pushes per-call latency above ~6s could still trigger throttling. A future iteration should track observed latency and back off automatically.

## Alternatives Considered

- **Per-call retries with exponential backoff.** Catches the rate limit and waits. Rejected because it masks the underlying problem (peak demand exceeds capacity) and creates unpredictable wall-clock time. Caller cannot bound latency at the orchestration level.
- **Provider-side rate limiter (e.g. `aiolimiter`).** Token-bucket library that enforces requests/second. More precise than our semaphore + sleep, but the actual constraint is **input-tokens-per-minute**, not requests/second. Token counting requires post-call accounting and can't bound a call before it fires. Rejected as a poor fit for the actual rate-limit semantics.
- **Smaller batches with serial execution.** Process one vendor at a time. Rejected because total wall time scales with vendor count linearly, with no concurrency benefit when slack capacity exists.
- **Higher provider tier.** The simplest fix -- pay for Tier 2 or 3 with higher TPM. Rejected for portfolio purposes (the goal is demonstrating the design, not bypassing the constraint), though documented as an option for production deployments.

## Validation

- Two successful E2E runs against OpenAI Tier 1 at production tuning. Zero rate-limit retries, zero failures.
- Test suite runs in 6.4s with conftest overrides applied (verified against 100+ second regression when overrides were missing).
- LangSmith dashboard confirms steady call cadence: P50 latency 1.62s, P99 5.39s, no failed calls attributed to throttling.

## Related

- [ADR-0001](0001-provider-agnostic-llm-factory.md) -- The factory whose abstractions this concurrency layer wraps.
- [ADR-0003](0003-langsmith-env-propagation.md) -- The propagation fix that surfaced the test-environment slowdown described above.
