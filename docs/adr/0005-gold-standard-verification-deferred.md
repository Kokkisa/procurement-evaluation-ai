# ADR 0005: Defer Gold-Standard Verification Fix

- **Status:** Accepted
- **Date:** Block 10 (post-OpenAI E2E run)
- **Decision-maker:** Project lead

## Context

The end-to-end test script (`scripts/run_eval_test.py`) prints a "Gold-standard accept/reject split" comparison after each run, comparing the system's per-vendor verdicts against a hand-curated expected outcome.

After the Block 10 OpenAI migration, this comparison reports `MISSING` for all five vendors:

```
GOLD-STANDARD ACCEPT/REJECT SPLIT
=================================
[!!] AROHA FACILITY SERVICES PVT LTD                    -> MISSING   (expected ACCEPTED)
[!!] TEJASWINI HOUSEKEEPING ENTERPRISES                  -> MISSING   (expected ACCEPTED)
[!!] SHRI MANGALAM SAFAI WORKS                           -> MISSING   (expected REJECTED)
[!!] PRABHAT DEEP SANITATION SOLUTIONS                   -> MISSING   (expected ACCEPTED)
[!!] RAGHAVENDRA MAINTENANCE WORKS                       -> MISSING   (expected REJECTED)

FAIL: Gold-standard split mismatch.
```

This output is alarming at first read. Investigation showed the system is actually correct -- the script's comparison logic is wrong.

**System behavior** (verified in the generated PDF):

| Vendor | Technical verdict | Commercial verdict | Combined |
|---|---|---|---|
| AROHA FACILITY SERVICES | ACCEPTED | REJECTED (no commercial docs) | REJECTED |
| TEJASWINI HOUSEKEEPING | ACCEPTED | REJECTED | REJECTED |
| SHRI MANGALAM SAFAI | REJECTED | REJECTED | REJECTED |
| PRABHAT DEEP SANITATION | ACCEPTED | REJECTED | REJECTED |
| RAGHAVENDRA MAINTENANCE | REJECTED | REJECTED | REJECTED |

The technical-side verdicts match the gold standard exactly (3 ACCEPTED, 2 REJECTED). Commercial verdicts are all REJECTED because the synthetic test fixture lacks commercial bid documents -- this is correct system behavior, not a bug.

**Script bug:** The verification reads from a single combined-verdict field. Because all five vendors are REJECTED on combined verdict (due to the missing commercial docs), the script can't match them to the technical-only gold-standard expectations and reports MISSING.

## Decision

**Document the discrepancy as a known-issue and defer the verification-script fix to v0.2.**

Rationale:

1. **The system is provably correct.** The PDF technical evaluation matrix shows the correct per-vendor verdicts. The LangSmith trace tree shows every criterion was evaluated with the expected reasoning. The audit log captures all five lifecycle events. None of these depend on the verification script.
2. **The bug is in test tooling, not in the system.** The verification script is a developer convenience that runs after the full pipeline. It does not affect what the system produces -- it only affects whether a CLI banner says "PASS" or "FAIL".
3. **The fix is non-trivial relative to its value.** A correct fix requires splitting the gold-standard fixture into `tech_expected` and `comm_expected` fields, updating the comparison logic to read both, and accounting for the combined-verdict propagation rules. Estimated 2-3 hours of careful work for a cosmetic improvement. That budget is better spent on the v0.2 cascade work or the Streamlit reviewer UI.
4. **Recruiters and engineers reviewing the repo will not see this output.** The repo's portfolio surface is the README, the PDF report, and the LangSmith dashboard. The verification script is interior tooling.

## Consequences

### Positive

- **No engineering time spent on cosmetic fixes during the v0.1 closeout.** The deferred work is documented (`docs/known-issues.md`, this ADR) and tracked.
- **Honest documentation pattern.** Future contributors and reviewers see the discrepancy explicitly called out, including the evidence that the system is correct. This is more credible than silently fixing the script and pretending the issue never existed.
- **Forces v0.2 to plan around real evaluation infrastructure.** Splitting the gold standard properly is a stepping stone to the labeled-borderline-case dataset that [ADR-0004](0004-multi-model-cascade-proposed.md) requires anyway. Bundling these two efforts in v0.2 is more efficient than doing them separately.

### Negative

- **The CLI output looks alarming on first run.** A new contributor running `python scripts/run_eval_test.py` will see "FAIL: Gold-standard split mismatch" and may assume the system is broken. Mitigated by:
  - Prominent reference to this ADR and `docs/known-issues.md` in the README's "What's Next" section.
  - A comment block in `scripts/run_eval_test.py` itself flagging the known issue.
- **Trust cost.** A "FAIL" message that means "everything works, the script is wrong" is genuinely confusing. We accept this temporarily for the v0.1 release.

## Alternatives Considered

- **Fix it now.** Spend 2-3 hours on the split-fixture refactor. Rejected because the time is better spent on the README + ADR documentation that recruiters will actually see during v0.1.
- **Suppress the FAIL line.** Comment out the gold-standard comparison entirely. Rejected because it hides information rather than acknowledging it -- worse than the current state.
- **Replace the comparison with a stub that always says PASS.** Worse than suppression. Rejected.
- **Rewrite the gold-standard fixture to expect the combined verdicts.** Would make the script pass without code changes, but bakes in the wrong test semantics (the gold standard would now claim AROHA should be REJECTED, which contradicts the actual technical evaluation). Rejected as misleading.

## Validation

System correctness is verified by three independent artifacts:

- **Final PDF** -- `data/outputs/DEMO_2026_HKP_001_iter1_technical_evaluation.pdf` shows correct per-vendor verdicts in the technical evaluation matrix (3 ACCEPTED, 2 REJECTED, matching gold standard).
- **LangSmith trace tree** -- 305 traces across two E2E runs, with every criterion evaluation captured. Drilling into individual criterion runs confirms the model's reasoning matches the verdict it produces.
- **Audit log** -- 6 lifecycle events recorded per run (uploaded, metadata_extracted, metadata_confirmed, evaluation_generated, sent_for_review, review_accepted). All five vendors traverse the lifecycle without error.

The verification script's MISSING report contradicts none of these. It is a comparison-logic bug, not a system bug.

## Promotion criteria (v0.2)

To resolve this ADR and remove the known-issue:

1. Refactor `tests/fixtures/gold_standard.json` (or equivalent) to split per-vendor expectations into `tech_expected` and `comm_expected`.
2. Update the comparison logic in `scripts/run_eval_test.py` to read both fields and report tech and commercial verdicts separately.
3. Add an integration test that asserts the verification script returns a clean PASS against the current synthetic fixture.
4. Update `docs/known-issues.md` and this ADR to reflect resolution.

## Related

- [docs/known-issues.md](../known-issues.md) -- User-facing documentation of the discrepancy.
- [ADR-0004](0004-multi-model-cascade-proposed.md) -- The v0.2 work that this fix bundles cleanly with.
