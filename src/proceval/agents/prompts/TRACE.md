# Agent trace structure (LangSmith)

LangChain emits trace data automatically when `LANGCHAIN_TRACING_V2=true`,
`LANGCHAIN_API_KEY` is set, and `LANGCHAIN_PROJECT` names the project. Our
agents do not call any tracing code directly — composition with
`prompt | model.with_structured_output(Schema)` is enough.

## What gets traced

Each agent invocation produces **one trace** (a tree of runs) per call:

| Agent                       | Trace name           | Child runs                        |
|-----------------------------|----------------------|-----------------------------------|
| MetadataExtractionAgent     | `RunnableSequence`   | ChatPromptTemplate, ChatAnthropic |
| CriteriaExtractionAgent     | `RunnableSequence`   | ChatPromptTemplate, ChatAnthropic |
| VendorEvaluationAgent (per criterion call) | `RunnableSequence` | ChatPromptTemplate, ChatAnthropic |

A full `/confirm` request fans out to:
- 1 metadata trace (already done at `/ingest` time, replayed here only on re-eval)
- 1 criteria trace
- N vendors × M criteria evaluation traces

A full `/review/reject` re-evaluation triples the count (same chain rerun
with `feedback_section` populated).

## Linking from PDF audit log → trace

The lifecycle audit log (printed in the final PDF appendix and via
`GET /audit/{eval_id}`) records every state transition with timestamps.
A reviewer who wants to inspect *what the LLM actually saw* for a given
evaluation can search LangSmith with:

```
project: procurement-evaluation-ai
filter:  start_time > <metadata_extracted timestamp>
filter:  start_time < <evaluation_generated timestamp>
```

Or, if `extra_tags` are set on the chain (future extension), filter
directly by `eval_id=<UUID>`.

Direct project link template:
```
https://smith.langchain.com/o/me/projects/p/{LANGCHAIN_PROJECT}
```

The runner script `scripts/run_eval_test.py` prints this link (substituted
with the project from settings) at the end of each E2E pass, so a reviewer
can navigate to LangSmith straight from the demo output.

## Disabling tracing

Set `LANGCHAIN_TRACING_V2=false` (or unset entirely) in `.env`. The agents
keep working — `with_structured_output` doesn't depend on tracing — and no
network calls go to LangSmith. All tests remain green.
