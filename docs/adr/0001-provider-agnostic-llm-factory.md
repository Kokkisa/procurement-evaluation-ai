# ADR 0001: Provider-Agnostic LLM Factory

- **Status:** Accepted
- **Date:** Block 5 (initial), reaffirmed Block 10 (provider migration)
- **Decision-maker:** Project lead

## Context

The system makes LLM calls from multiple agent types (criteria extraction, technical evaluation, commercial evaluation, audit synthesis). Each call is structured-output (Pydantic schema) and async.

We needed to choose an integration pattern with three properties:

1. **Provider portability** -- swap between OpenAI, Anthropic, and local Ollama without rewriting agent code.
2. **Auto-instrumentation** -- LangSmith traces emit without each agent calling tracing primitives.
3. **Composability** -- chain prompts, output parsers, and post-processing without scaffolding boilerplate.

Two viable options existed:

- **Option A: Raw provider SDKs** -- Call `openai.OpenAI(...)` and `anthropic.Anthropic(...)` directly. Maximum control, minimal dependencies.
- **Option B: LangChain wrappers** -- Use `ChatOpenAI`, `ChatAnthropic`, `ChatOllama`. Slightly more abstraction, plus auto-tracing and Runnable composition for free.

## Decision

**Adopt Option B (LangChain wrappers) and isolate provider selection behind a factory function.**

A small module (`src/proceval/llm_factory.py`) exposes `get_chat_model()`. It reads `settings.llm_provider` and returns the configured wrapper:

```python
def get_chat_model() -> BaseChatModel:
    if settings.llm_provider == "openai":
        return ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key, ...)
    if settings.llm_provider == "anthropic":
        return ChatAnthropic(model=settings.anthropic_model, api_key=settings.anthropic_api_key, ...)
    if settings.llm_provider == "ollama":
        return ChatOllama(model=settings.ollama_model, base_url=settings.ollama_base_url, ...)
    raise ValueError(...)
```

Agents call `get_chat_model()` rather than instantiating a wrapper directly. They then compose with prompts and structured-output schemas via the LangChain Runnable interface:

```python
chain = prompt | model.with_structured_output(EvaluationResult)
result = await chain.ainvoke({"vendor_doc": ..., "criterion": ...})
```

## Consequences

### Positive

- **Provider switch is a config change.** Block 10 hit Anthropic Tier 1 rate limits (30K input TPM ceiling, ~135K TPM peak required). The fix was a 3-line edit to `.env` (`LLM_PROVIDER=anthropic` -> `openai`, plus an OpenAI API key). No agent code touched. Zero rebuilds, zero new tests.
- **LangSmith auto-tracing.** Setting `LANGCHAIN_TRACING_V2=true` plus `LANGCHAIN_API_KEY` is enough -- every `chain.ainvoke()` emits a trace automatically. No tracer instrumentation in agent code. Verified in production with 305 traces across two end-to-end runs.
- **Structured output is one method call.** `model.with_structured_output(Schema)` returns a Runnable that validates against the Pydantic schema. Without LangChain, every agent would hand-roll JSON extraction + Pydantic validation + retry-on-parse-error.
- **Composability.** Pre-processing, retries, and post-processing slot in as additional Runnables in the chain without wrapping the model object.

### Negative

- **Adds LangChain as a dependency.** ~50MB transitive footprint, version sensitivity (LangChain releases break minor APIs frequently). Mitigated by pinning specific versions in `requirements.txt`.
- **Slight indirection during debugging.** A failing LLM call surfaces a LangChain stack trace rather than a raw provider exception. Mitigated by LangSmith trace inspection and error wrapping in agent code.
- **`pydantic-settings` does not export to `os.environ`.** A subtle consequence: LangChain's auto-tracer reads `os.environ` directly, but `pydantic-settings` only loads into the `Settings` object. This caused traces to silently fail until propagation was added. Documented separately in [ADR-0003](0003-langsmith-env-propagation.md).

## Alternatives Considered

- **Raw SDK + custom tracing.** Would require building our own trace emission layer (LangSmith POST API, child run hierarchy, token counting). Estimated 2-3 weeks of work for parity with LangChain's automatic instrumentation. Rejected as undifferentiated heavy lifting.
- **Litellm or other thin proxy.** Cleaner API surface than LangChain but loses structured-output validation and Runnable composition. Would force re-implementing those layers ourselves. Rejected.
- **Direct OpenAI-only with no abstraction.** Simplest possible code, but locks us out of Anthropic and local Ollama. Rejected because portfolio value depends on showing provider-agnostic design.

## Validation

- Block 10 OpenAI migration: 3-line `.env` change, zero agent code changes, full E2E pass within 30 minutes including verification.
- 149 tests pass against both providers (provider tests gated by `RUN_LIVE_LLM_TESTS=1`).
- LangSmith dashboard shows automatic tracing for both `ChatOpenAI` and `ChatAnthropic` calls without code changes.
