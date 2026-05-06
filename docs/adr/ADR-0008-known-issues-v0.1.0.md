# ADR 0008: Known Issues at v0.1.0 Tag — Deferred Fixes

* **Status:** Accepted
* **Date:** Block 15 (v0.1.0 cut, post real-data validation)
* **Decision-maker:** Project lead

## Context

Block 14's per-document fan-out (see [ADR-0007](0007-per-document-evaluation.md)) was validated end-to-end on a real 3-vendor PSU procurement bid pack on 2026-05-06: 23 documents, 9 criteria, ~207 LLM calls, ~$0.50 spend, full lifecycle (`/ingest → /confirm → /review/accept → /approve`) ran clean. The AI's technical accept/reject split (one vendor ACCEPTED; two vendors REJECTED on missing PAN) matched the human evaluator's decision. The system also flagged a missing self-attestation on a PAN submission — a verification step a human reviewer skimming 23 PDFs could plausibly miss, and a legitimate v0.1.0 feature highlight for the Loom.

Three small issues surfaced during that run. None block the v0.1.0 tag — the system produces correct accept/reject decisions and an auditable PDF in real-world conditions — but each is worth recording as deferred work so v0.2.0 doesn't rediscover them.

## Decision

Tag v0.1.0 as-is and capture the three findings here. Each fix lands in its own follow-up block (15.1 / 15.2 / 15.3) post-tag, gated on the same suite-green discipline used through Blocks 1–14.

## Issue 15.1 — VerdictPerDoc enum leak on document criteria with embedded values

**Symptom.** On the real-data run, `PQC_DOC_UDYAM_MSME` and `PQC_DOC_GST` came back with `verdict="VALUE"` on some vendors instead of `PROVIDED` or `NOT_PROVIDED`. The Udyam registration number and GSTIN are valid identifiers (and the document is genuinely present), so the LLM is putting the identifier value into the `extracted_value` field and apparently flipping the verdict from `MEETS` to a value-bearing shape that the aggregator then maps to `VALUE` in the resulting `CriterionEvaluation`.

**Suspected root cause.** Block 14 schema regression in the per-doc verdict path (ADR-0007). `aggregate_document_verdicts()` in `src/proceval/agents/evaluation_agent.py` collapses a list of `VerdictPerDoc` into one `CriterionEvaluation`. The current rule:

```
if chosen.extracted_value:
    return CriterionEvaluation(verdict="VALUE", ...)
return CriterionEvaluation(verdict="PROVIDED", ...)
```

This was correct for criteria where `extracted_value` *only* appears with numeric thresholds (`PQC_FIN_TURNOVER`, `PQC_TECH_SIMILAR_WORK`). For document-existence criteria with an identifier in the document body (Udyam reg number, GSTIN, PAN), the per-doc agent legitimately fills `extracted_value` and the aggregator wrongly decides "this is a VALUE-typed criterion" rather than "this is a PROVIDED document that happens to carry an ID for reference".

**Scope of impact.** Cosmetic at the matrix-cell level: the cell shows a green VALUE pill with the identifier instead of a green PROVIDED tick. The accept/reject decision is unaffected because `threshold_met=True` is still reached on these cells. The downstream `verdict.compute_overall_verdict()` treats VALUE-with-`threshold_met=True` identically to PROVIDED.

**Deferred-fix rationale.** Wrong cell label, right vendor verdict. Tagging now lets the v0.1.0 release demonstrate the right outcomes; the cosmetic mismatch is fixable without touching any of the load-bearing logic.

**Target fix (Block 15.1).** Use the criterion's own `type` (the existing `CriterionType.DOCUMENT` vs `CriterionType.FINANCIAL` / `CriterionType.TECHNICAL` distinction) as the disambiguator inside the aggregator: a DOCUMENT-typed criterion always collapses to `PROVIDED` / `NOT_PROVIDED` regardless of whether `extracted_value` is set; only FINANCIAL / TECHNICAL criteria with a `threshold_value` collapse to `VALUE`. One-line conditional in `aggregate_document_verdicts()`. Add a regression test that supplies a DOCUMENT criterion + a `MEETS` per-doc verdict with `extracted_value="UDYAM-AB-12-3456789"` and asserts `verdict == "PROVIDED"` not `"VALUE"`.

## Issue 15.2 — PDF filename missing eval_id prefix; collision risk on multi-run dirs

**Symptom.** The Block 9 generator writes to `{tender_number_safe}_iter{N}_technical_evaluation.pdf`. On a real run with `tender_number=""` (or any falsy/sanitization-stripped tender number) the filename collapses to `_iter1_technical_evaluation.pdf`. Today's run produced exactly that filename. Two runs of the same tender (or two runs with empty tender numbers) overwrite each other under `data/outputs/`.

**Suspected root cause.** `generate_final_pdf()` in `src/proceval/pdf/report_generator.py` derives the safe filename from `metadata.tender_number` only:

```python
safe = metadata.tender_number.replace("/", "_").replace("\\", "_").replace(" ", "_")
out = output_dir / f"{safe}_iter{iteration}_technical_evaluation.pdf"
```

If `tender_number` is empty string (or just punctuation that all gets sanitised to empty), `safe == ""` and the filename starts with `_iter`. There's no `eval_id` in the filename to disambiguate.

**Scope of impact.** Single-deployment-only collision risk. In practice today's run produced exactly one PDF and was approved fine — the path string went into the audit_log row's notes for forensic recovery. But two concurrent evaluations of the same tender (or two runs where metadata extraction returns an empty tender_number) would clobber each other in `data/outputs/`.

**Deferred-fix rationale.** No data lost on today's run; the audit_log captures the path. Easy to fix without affecting any other code path.

**Target fix (Block 15.2).** Prepend the first 8 chars of `eval_id` to the filename so it's always unique even if `tender_number` is empty: `{eval_id_short}_{tender_number_safe}_iter{N}_technical_evaluation.pdf`. Update `test_pdf_generation.py::test_pdf_filename_includes_iteration` to also assert the eval_id prefix is present. Update `test_pdf_iteration_number_changes_filename` to keep working under the new shape.

## Issue 15.3 — `curl` against POST endpoints returns 422 from PowerShell

**Symptom.** Every endpoint that takes a JSON body (`POST /confirm`, `POST /review/{accept,reject}`, `POST /approve`, `POST /push`) returns `422 Unprocessable Entity` when invoked from PowerShell with `curl -X POST -d '{"actor_id":"..."}'`. Reproduces reliably on Windows 10 / 11 default PowerShell.

**Suspected root cause.** PowerShell aliases `curl` (and `wget`) to its native `Invoke-WebRequest` cmdlet, which has incompatible argument semantics: `-X POST` is parsed as a parameter name, the `-d` payload becomes a positional argument that gets URL-encoded into the query string instead of the body, and the `Content-Type` header is never set. FastAPI sees an empty body where it expects JSON and returns 422 from the Pydantic validator.

**Scope of impact.** Documentation / DX only. Zero runtime impact on the deployed system. Affects Windows users following the README's `curl` examples; macOS / Linux / Git Bash all use real curl and work fine.

**Deferred-fix rationale.** The fix is documentation, not code. Block 15 lands a short "Calling the API from Windows PowerShell" section in the README pointing operators at `Invoke-RestMethod -ContentType "application/json" -Body '{"actor_id":"..."}'` (Windows native) or `bash -c "curl ..."` (Git Bash). No further changes need to land *post-v0.1.0*; calling out as a known issue here purely for the audit trail.

**Target fix (Block 15.3 — already shipped in this block).** Done in Block 15 README polish. Listed here for completeness so the three findings sit together.

## Consequences

### Positive
- v0.1.0 ships with full transparency about its rough edges. Reviewers reading the repo see the system was honestly tested against real data and that the issues found are documented + scoped, not hidden.
- Each issue has a target block (15.1 / 15.2 / 15.3) so the post-v0.1.0 work is structured and bounded.
- The pattern "tag → record known issues → continue" is the right release discipline for a v0.1.0 portfolio cut. Blocking on cosmetic drift would have delayed real-data validation.

### Negative
- README readers may notice the cosmetic VALUE-vs-PROVIDED mismatch on document criteria in the Loom screenshots. Mitigation: the Loom script (`LOOM_SCRIPT.md`) calls this out explicitly under "Honest limitations" so it doesn't read as oversight.
- The PDF filename issue is real if anyone deploys multi-tenant before 15.2 lands. Documented in the README's "Calling the API from Windows" section + here.

## Cross-references

- [ADR-0007 (per-document evaluation)](0007-per-document-evaluation.md) — Issue 15.1 is a Block 14 schema regression; the fix lives in `aggregate_document_verdicts()` introduced by ADR-0007.
- [README §Real-data validation](../../README.md) — operator-facing summary of the validation run.
- [LOOM_SCRIPT.md §5 Honest limitations](../../LOOM_SCRIPT.md) — verbal callout for the recording.
