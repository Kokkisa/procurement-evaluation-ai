# ADR 0007: Per-Document Evaluation for Production-Scale Vendor Inputs

* **Status:** Accepted
* **Date:** Block 14 (post real-data validation run)
* **Decision-maker:** Project lead

## Context

Block 13's hybrid OCR fallback enabled the system to ingest real Indian procurement documents. The first end-to-end run on a real PSU bid pack (7 vendors, 56 PDFs, 107 MB total, ~50% scanned) exposed a fundamental scaling gap in the vendor evaluation agent.

The current architecture concatenates all OCR-extracted text from all of a vendor's documents into a single prompt, then evaluates that vendor against the full criteria set in one LLM call. On synthetic test fixtures (small clean PDFs), this produces ~10K-20K token prompts — well within model limits. On real OCR-heavy enterprise data, a single vendor's concatenated text can exceed 100K tokens.

The failure was concrete and reproducible. One vendor in the real bid pack, with 8 PDFs totaling 36 MB (mostly notarized scans), produced a vendor evaluation prompt of 139,269 tokens against gpt-4o-mini's 128,000-token context ceiling. The call returned `openai.BadRequestError: context_length_exceeded` after 22 minutes of upstream pipeline work.

This is not a rate-limit problem (those are solved by ADR-0002). This is a per-call payload-size problem. No amount of concurrency tuning, sleep adjustment, or retry logic can split a 139K-token request into something the model accepts. The input itself must be reshaped.

Three properties were needed:

1. Bounded per-call token count — every LLM call must fit comfortably under 100K tokens.
2. No silent truncation — in procurement, the disqualifying clause is often buried deep in a single document.
3. Auditable per-document reasoning — when a vendor is rejected, a human reviewer should see which document drove the rejection.

## Decision

Replace the single per-vendor LLM call with a fan-out over (vendor x document x criterion) tuples. Each LLM call evaluates one criterion against one document for one vendor. The Vendor Evaluation Agent then aggregates per-document verdicts into a per-vendor verdict for each criterion using deterministic rules, no second LLM call.

For each (vendor, criterion) pair: iterate over the vendor's documents, prompt the LLM with criterion + that single document's text, LLM returns MEETS | DOES_NOT_MEET | NOT_APPLICABLE plus extracted value + reasoning. Aggregate across documents per criterion: any MEETS wins; else if all NOT_APPLICABLE then criterion is unevaluable; else DOES_NOT_MEET with strongest negative as cited evidence.

The aggregation logic is deterministic Python, no LLM. This mirrors the verdict.py pattern from Block 5.

## Consequences

### Positive
- Bounded token count by construction
- Per-document reasoning visible in LangSmith
- Auditability matches procurement reality
- Aggregation rules are inspectable

### Negative
- Cost increases ~8x per vendor (still under $1.50 per full eval at gpt-4o-mini pricing)
- Wall-clock runtime increases proportionally to call count
- "Any MEETS wins" is a documented business rule decision

### Limitations (deferred to v0.3)
- Multi-document criteria (e.g. "turnover trend across 3 years") need join-aware aggregation
- Implicit document classification could become explicit pre-classification pass (ADR-0008 candidate)

## Alternatives Considered
- Smart chunking inside a single per-vendor call: rejected — arbitrary chunk boundaries make audit fragile.
- Classification-first routing: deferred to v0.3 — real engineering, not a chunking refactor.
- Upgrading to gpt-4o 200K context: rejected — 16x cost, just a higher cliff, doesn't fix auditability.

## Validation
Validated when: the 3-vendor real-data run (Vendor A / Vendor B / Vendor C, ~17 MB total) completes /confirm successfully end-to-end; the PDF report shows per-criterion verdicts with at least one cited document per verdict; LangSmith traces show all per-document calls under 50K input tokens.
