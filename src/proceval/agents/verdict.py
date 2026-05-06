"""Deterministic post-processor that turns per-criterion LLM outputs into the
overall ACCEPTED/REJECTED verdict + a structured remarks string.

The LLM is responsible for the per-criterion judgment (verdict + threshold_met
+ extracted_value); this module is pure logic -no LLM, no I/O -so the
accept/reject decision and the remarks wording are reproducible and auditable.

Decision rule (matches spec §7.3):
- ACCEPTED iff every required criterion is satisfied:
    * PROVIDED  → pass (document-existence criteria)
    * VALUE     → pass iff threshold_met is True
    * NOT_PROVIDED, PARTIAL → fail
- Any failing criterion → REJECTED, with the failure(s) named in the remarks.
"""

from __future__ import annotations

from typing import Literal

from ..schemas.tender import EvalCriterion
from ..schemas.vendor import CriterionEvaluation

OverallVerdict = Literal["ACCEPTED", "REJECTED"]


def compute_overall_verdict(
    vendor_name: str,
    is_msme: bool,
    criteria: list[EvalCriterion],
    criterion_evaluations: list[CriterionEvaluation],
) -> tuple[OverallVerdict, str]:
    """Return the (overall_verdict, overall_remarks) for one vendor.

    ``criteria`` and ``criterion_evaluations`` are joined by ``criterion_id``;
    evaluations that don't correspond to any known criterion are ignored.
    """
    by_id: dict[str, EvalCriterion] = {c.id: c for c in criteria}
    failures: list[str] = []

    for ev in criterion_evaluations:
        criterion = by_id.get(ev.criterion_id)
        if criterion is None:
            continue

        verdict = ev.verdict.upper() if isinstance(ev.verdict, str) else str(ev.verdict).upper()

        if verdict == "PROVIDED":
            continue
        if verdict == "NOT_PROVIDED":
            failures.append(f"did not provide {criterion.name}")
            continue
        if verdict == "VALUE":
            if ev.threshold_met is False:
                failures.append(_format_threshold_failure(criterion, ev, is_msme))
            continue
        if verdict == "PARTIAL":
            failures.append(_format_partial_failure(criterion, ev))
            continue
        # Defensive: unknown verdict is treated as failure to avoid silent passes.
        failures.append(f"returned unrecognised verdict {ev.verdict!r} for {criterion.name}")

    if not failures:
        return (
            "ACCEPTED",
            f"All {len(criterion_evaluations)} evaluated criteria are satisfied. "
            f"Vendor is technically qualified.",
        )

    if len(failures) == 1:
        body = failures[0]
    else:
        body = "; ".join(failures)
    return ("REJECTED", f"Vendor {body}. Hence rejected.")


def _applied_threshold(criterion: EvalCriterion, is_msme: bool) -> tuple[float | None, bool]:
    """Return (threshold_used, used_relaxation_flag)."""
    if is_msme and criterion.msme_relaxation_value is not None:
        return (criterion.msme_relaxation_value, True)
    return (criterion.threshold_value, False)


def _format_threshold_failure(
    criterion: EvalCriterion,
    ev: CriterionEvaluation,
    is_msme: bool,
) -> str:
    threshold, used_relaxation = _applied_threshold(criterion, is_msme)
    if threshold is None:
        # Shouldn't really happen -VALUE verdicts come with a threshold -but
        # be defensive so we never crash on a malformed criterion.
        return (
            f"did not meet {criterion.name} (no threshold stated) -"
            f"provided value {ev.extracted_value or '(not extracted)'}"
        )
    suffix = " (MSME-relaxed)" if used_relaxation else ""
    value_str = ev.extracted_value or "(value not extracted)"
    return (
        f"did not meet {criterion.name} threshold of {threshold:.2f} Lakhs"
        f"{suffix} -provided value {value_str}"
    )


def _format_partial_failure(criterion: EvalCriterion, ev: CriterionEvaluation) -> str:
    detail = ev.reasoning.strip().rstrip(".")
    return f"only partially satisfied {criterion.name} ({detail})"
