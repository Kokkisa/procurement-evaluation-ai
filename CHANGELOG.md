# Changelog

All notable changes to Procurement Evaluation AI are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses [Semantic Versioning](https://semver.org/).

## [v0.1.0] — 2026-05-06

First end-to-end release. Validated on real PSU procurement data (3-vendor real-data bid pack: 23 documents, 9 criteria, ~207 LLM calls, ~$0.50 spend) — AI matched the human evaluator's accept/reject decision on every vendor and additionally surfaced a missing self-attestation on a PAN submission that a human reviewer skimming 23 PDFs could plausibly miss.

### Build sequence

Built across 14 blocks of focused work, captured commit-by-commit on `main`:

| Block | Scope |
|---|---|
| 1 | Repo scaffold, `pyproject.toml`, settings via `pydantic-settings` |
| 2 | Pydantic schemas + SQLAlchemy models + first Alembic migration |
| 3 | PDF ingestion (`pdfplumber` primary + `pypdf` fallback) + zip handling |
| 4 | Synthetic 5-vendor housekeeping fixtures with deterministic generator |
| 5 | Metadata + Criteria extraction agents (LangChain `with_structured_output` + retry) |
| 6 | Vendor evaluation agent + deterministic `verdict.compute_overall_verdict()` |
| 7 | FastAPI routes (`/ingest /confirm /review/{accept,reject} /approve /push /audit /health`) + audit_log on every state transition |
| 8 | Streamlit UI: state-driven routing + role switcher + matrix table |
| 9 | Final PDF generator (ReportLab, A4 landscape, 4-page audit-grade layout) |
| 10 | LangSmith observability + bounded concurrency (ADR-0002) + os.environ propagation (ADR-0003) |
| 11 | README + 5 ADRs + ARCHITECTURE.md (interview-grade docs) |
| 12 | (Subsumed into 11/13 polish.) |
| 13 | Hybrid PDF extraction with Tesseract OCR fallback (ADR-0006) |
| 14 | Per-(vendor × criterion × document) fan-out + deterministic aggregator (ADR-0007) |
| 15 | v0.1.0 release cut: ADR-0008 known issues, README polish, CHANGELOG, Loom script |

### Key features

- **Multi-agent evaluation pipeline** — Metadata Agent → Criteria Extraction Agent → Vendor Evaluation Agent (per-document). Each agent uses `with_structured_output(Pydantic)` for type-safe LLM I/O with bounded retry on validation errors.
- **Hybrid PDF extraction** — pdfplumber's text layer first; Tesseract OCR fallback per page when the text layer falls below `OCR_FALLBACK_THRESHOLD`. Handles real bid packs that mix digital docs with notarised scans. ([ADR-0006](docs/adr/0006-hybrid-pdf-extraction.md))
- **Per-document fan-out** — for each (vendor, criterion) pair, one LLM call per document; deterministic `aggregate_document_verdicts()` collapses per-doc verdicts to a per-criterion result (any `MEETS` wins; else strongest `DOES_NOT_MEET` cited; else `NOT_APPLICABLE` flagged). Bounds per-call payload size and gives auditable per-document reasoning. ([ADR-0007](docs/adr/0007-per-document-evaluation.md))
- **Audit-grade PDF report** — ReportLab-based, A4 landscape, 4-page layout: header band, tender metadata, vendor list, technical + commercial evaluation matrices with verdict-coded cells, OVERALL REMARKS row, lifecycle audit log appendix, signature blocks.
- **Lifecycle audit log** — every state transition (`uploaded`, `metadata_extracted`, `metadata_confirmed`, `evaluation_generated`, `sent_for_review`, `review_accepted` / `review_rejected` / `re_evaluation_triggered`, `approved`, `complete_and_pushed`) writes a row to `audit_log` with actor, role, notes, timestamp. The PDF appendix is a chronological table of these events.
- **FastAPI service** — eight endpoints (`/ingest /confirm /review/{accept,reject} /approve /push /audit /health`) with idempotent transitions and Pydantic request/response models.
- **Streamlit UI** — state-driven routing: the visible screen is a function of `(role, eval_id, status)`; user navigates by switching role in the sidebar.
- **PostgreSQL persistence** — four tables (`evaluations`, `audit_log`, `archive`, `documents`), Alembic migrations, JSONB columns for full evaluation reconstruction.
- **LangSmith observability** — set `LANGCHAIN_TRACING_V2=true` and traces fire for every agent call automatically. `_propagate_langsmith_to_environ()` mirrors `.env` values into `os.environ` so the LangChain auto-tracer picks them up. ([ADR-0003](docs/adr/0003-langsmith-env-propagation.md))
- **Provider-agnostic LLM** — `ChatOpenAI`, `ChatAnthropic`, `ChatOllama` interchangeable via `LLM_PROVIDER`. ([ADR-0001](docs/adr/0001-provider-agnostic-llm-factory.md))
- **Bounded concurrency** — global `asyncio.Semaphore` (`LLM_MAX_CONCURRENCY`) plus inter-batch sleep (`LLM_INTER_BATCH_SLEEP_SECONDS`) keep fan-out under provider rate limits. ([ADR-0002](docs/adr/0002-bounded-concurrency-orchestration.md))
- **174-test suite** — unit + mocked integration tests run in ~10s offline; 14 live-LLM tests gated behind `RUN_LIVE_LLM_TESTS=1` for billed pre-release validation.

### Real-data validation (this release)

* Tender: real PSU procurement bid pack (3-vendor)
* 3 vendors (referred to as Vendor A / Vendor B / Vendor C), 23 PDFs, ~50% scanned
* 9 criteria, ~207 LLM calls, ~$0.50 USD spend
* Technical: Vendor A ACCEPTED; Vendors B + C REJECTED on missing PAN — matches human evaluation
* Commercial: all 3 ACCEPTED
* AI flagged a missing self-attestation on a PAN submission — a verification step a human reviewer skimming 23 PDFs could plausibly miss
* Full lifecycle (`/ingest → /confirm → /review/accept → /approve`) ran clean within configured timeouts

### Known issues at this tag (see [ADR-0008](docs/adr/ADR-0008-known-issues-v0.1.0.md))

1. **Schema label leak (Block 15.1)** — Document criteria with embedded identifiers (Udyam, GSTIN) sometimes render with `verdict="VALUE"` instead of `PROVIDED`. Cosmetic; accept/reject decision is unaffected. Cross-references [ADR-0007](docs/adr/0007-per-document-evaluation.md) for the schema regression source.
2. **PDF filename missing `eval_id` prefix (Block 15.2)** — Empty-tender-number runs collapse to `_iter1_technical_evaluation.pdf`. Single-run-only collision risk; audit_log captures the actual path for forensic recovery.
3. **PowerShell `curl` ergonomics (Block 15.3 — fixed in this release)** — README now documents `Invoke-RestMethod` as the Windows-native equivalent of the macOS / Linux `curl` examples.

### Tech stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI | Async-native, structured-output-friendly |
| LLM orchestration | LangChain Runnables + `with_structured_output(Schema)` | Provider-agnostic, automatic LangSmith integration |
| LLM providers | OpenAI gpt-4o-mini (default), Anthropic Claude Sonnet 4.5, Ollama (local) | `LLM_PROVIDER` env-var swap |
| Observability | LangSmith | Per-call trace tree, token + cost rollup |
| Persistence | PostgreSQL 18 + SQLAlchemy 2.x + Alembic | Idempotent migrations, audit log primary store |
| PDF input | pdfplumber + pypdf + Tesseract (via pytesseract) + Poppler (via pdf2image) | Hybrid text-layer + OCR |
| PDF output | ReportLab Platypus | Deterministic, audit-grade |
| UI | Streamlit | State-driven routing, fast iteration |
| Test runner | pytest + pytest-asyncio | Unit + mocked integration + gated live-LLM layers |

### Operational requirements

- Python 3.11+
- PostgreSQL 14+ (18 used in development)
- An OpenAI API key (or Anthropic, or local Ollama)
- A LangSmith account + API key (optional, for tracing)
- Tesseract OCR + Poppler binaries (optional; required only for scanned-PDF support — install via `winget install UB-Mannheim.TesseractOCR` on Windows or `apt install tesseract-ocr poppler-utils` on Debian / Ubuntu)
