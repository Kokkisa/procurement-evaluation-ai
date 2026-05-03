"""Pure-logic unit tests for the deterministic verdict post-processor.

No LLM, no I/O — just exercises compute_overall_verdict() across all four
CriterionEvaluation verdict types (PROVIDED, NOT_PROVIDED, VALUE, PARTIAL),
the MSME-relaxation handling in the failure-message construction, and the
ACCEPTED/REJECTED decision rule.
"""

from __future__ import annotations

from proceval.agents import compute_overall_verdict
from proceval.schemas.tender import CriterionType, EvalCriterion
from proceval.schemas.vendor import CriterionEvaluation


# --- helpers ---------------------------------------------------------------


def _crit_doc(id_: str = "PQC_DOC_PAN", name: str = "PAN Card Submission") -> EvalCriterion:
    return EvalCriterion(
        id=id_,
        name=name,
        description=f"{name} required.",
        type=CriterionType.DOCUMENT,
    )


def _crit_financial(
    id_: str = "PQC_FIN_TURNOVER",
    name: str = "Average Annual Turnover",
    threshold: float = 100.0,
    msme: float | None = 85.0,
) -> EvalCriterion:
    return EvalCriterion(
        id=id_,
        name=name,
        description="Annual turnover threshold.",
        type=CriterionType.FINANCIAL,
        threshold_value=threshold,
        msme_relaxation_value=msme,
        aggregation_rule="average",
    )


def _crit_technical_similar_work() -> EvalCriterion:
    return EvalCriterion(
        id="PQC_TECH_SIMILAR_WORK",
        name="Similar Works Experience",
        description="Single similar-work PO threshold.",
        type=CriterionType.TECHNICAL,
        threshold_value=100.0,
        msme_relaxation_value=85.0,
        aggregation_rule="single_max",
    )


def _ev(criterion_id: str, verdict: str, **overrides) -> CriterionEvaluation:
    base = dict(
        criterion_id=criterion_id,
        verdict=verdict,
        reasoning="Source document found.",
        confidence=0.9,
    )
    base.update(overrides)
    return CriterionEvaluation(**base)


# --- ACCEPTED paths --------------------------------------------------------


def test_accepted_when_all_provided():
    criteria = [_crit_doc("PQC_DOC_PAN"), _crit_doc("PQC_DOC_GST")]
    evals = [_ev("PQC_DOC_PAN", "PROVIDED"), _ev("PQC_DOC_GST", "PROVIDED")]
    verdict, remarks = compute_overall_verdict("V", False, criteria, evals)
    assert verdict == "ACCEPTED"
    assert "All 2 evaluated criteria are satisfied" in remarks


def test_accepted_when_value_threshold_met():
    criteria = [_crit_financial()]
    evals = [
        _ev(
            "PQC_FIN_TURNOVER",
            "VALUE",
            extracted_value="120.50 LAKHS",
            threshold_met=True,
        )
    ]
    verdict, remarks = compute_overall_verdict("V", False, criteria, evals)
    assert verdict == "ACCEPTED"


def test_accepted_when_msme_relaxation_makes_value_pass():
    """An MSME vendor with 88.23 < 100 standard but >= 85 relaxed should pass.
    The post-processor trusts the LLM's threshold_met flag (which already
    accounted for relaxation) but uses is_msme to format the displayed
    threshold consistently when there IS a failure. Here: no failure.
    """
    criteria = [_crit_financial(threshold=100.0, msme=85.0)]
    evals = [
        _ev(
            "PQC_FIN_TURNOVER",
            "VALUE",
            extracted_value="88.23 LAKHS (3-yr avg, MSME)",
            threshold_met=True,  # LLM applied the 85.0 relaxation
        )
    ]
    verdict, _ = compute_overall_verdict("V", True, criteria, evals)
    assert verdict == "ACCEPTED"


# --- REJECTED paths: each verdict type independently ------------------------


def test_rejected_when_not_provided_for_required_doc():
    criteria = [_crit_doc("PQC_DOC_BLACKLIST_DECL", "Blacklisting Declaration")]
    evals = [
        _ev(
            "PQC_DOC_BLACKLIST_DECL",
            "NOT_PROVIDED",
            reasoning="Not found in submitted documents.",
        )
    ]
    verdict, remarks = compute_overall_verdict("V", False, criteria, evals)
    assert verdict == "REJECTED"
    assert "did not provide Blacklisting Declaration" in remarks
    assert remarks.endswith("Hence rejected.")


def test_rejected_when_value_threshold_not_met_non_msme():
    criteria = [_crit_technical_similar_work()]
    evals = [
        _ev(
            "PQC_TECH_SIMILAR_WORK",
            "VALUE",
            extracted_value="60.00 LAKHS",
            threshold_met=False,
        )
    ]
    verdict, remarks = compute_overall_verdict("V", False, criteria, evals)
    assert verdict == "REJECTED"
    assert "Similar Works Experience" in remarks
    assert "100.00 Lakhs" in remarks
    assert "MSME-relaxed" not in remarks  # non-MSME, no suffix
    assert "60.00 LAKHS" in remarks
    assert remarks.endswith("Hence rejected.")


def test_rejected_when_value_threshold_not_met_msme_uses_relaxed_threshold_in_remarks():
    criteria = [_crit_technical_similar_work()]
    evals = [
        _ev(
            "PQC_TECH_SIMILAR_WORK",
            "VALUE",
            extracted_value="38.42 LAKHS",
            threshold_met=False,
        )
    ]
    verdict, remarks = compute_overall_verdict("SHRI MANGALAM SAFAI WORKS", True, criteria, evals)
    assert verdict == "REJECTED"
    # Relaxation MUST be reflected in the displayed threshold
    assert "85.00 Lakhs" in remarks
    assert "(MSME-relaxed)" in remarks
    assert "38.42 LAKHS" in remarks
    assert "Similar Works Experience" in remarks


def test_rejected_when_msme_vendor_but_criterion_has_no_relaxation_uses_standard_threshold():
    crit = _crit_financial(threshold=200.0, msme=None)
    evals = [
        _ev(
            "PQC_FIN_TURNOVER",
            "VALUE",
            extracted_value="120.00 LAKHS",
            threshold_met=False,
        )
    ]
    _, remarks = compute_overall_verdict("V", True, [crit], evals)
    assert "200.00 Lakhs" in remarks
    assert "MSME-relaxed" not in remarks


def test_rejected_when_partial_verdict():
    criteria = [_crit_doc("PQC_DOC_PAN", "PAN Card Submission")]
    evals = [
        _ev(
            "PQC_DOC_PAN",
            "PARTIAL",
            reasoning="Only first page present, signature missing",
        )
    ]
    verdict, remarks = compute_overall_verdict("V", False, criteria, evals)
    assert verdict == "REJECTED"
    assert "only partially satisfied PAN Card Submission" in remarks
    assert "Only first page present" in remarks


# --- Composition / multiple failures ---------------------------------------


def test_multiple_failures_concatenated_with_semicolons():
    criteria = [
        _crit_doc("PQC_DOC_GST", "GST Registration Certificate"),
        _crit_technical_similar_work(),
    ]
    evals = [
        _ev("PQC_DOC_GST", "NOT_PROVIDED"),
        _ev(
            "PQC_TECH_SIMILAR_WORK",
            "VALUE",
            extracted_value="50.00 LAKHS",
            threshold_met=False,
        ),
    ]
    verdict, remarks = compute_overall_verdict("V", False, criteria, evals)
    assert verdict == "REJECTED"
    assert "did not provide GST Registration Certificate" in remarks
    assert "did not meet Similar Works Experience threshold of 100.00 Lakhs" in remarks
    assert remarks.startswith("Vendor ")
    assert remarks.endswith("Hence rejected.")
    # multi-failure separator
    assert "; " in remarks


def test_provided_passes_alongside_failures_only_failures_named():
    criteria = [
        _crit_doc("PQC_DOC_PAN", "PAN Card Submission"),
        _crit_doc("PQC_DOC_GST", "GST Registration Certificate"),
    ]
    evals = [
        _ev("PQC_DOC_PAN", "PROVIDED"),
        _ev("PQC_DOC_GST", "NOT_PROVIDED"),
    ]
    verdict, remarks = compute_overall_verdict("V", False, criteria, evals)
    assert verdict == "REJECTED"
    assert "PAN Card Submission" not in remarks  # not mentioned because it passed
    assert "GST Registration Certificate" in remarks


def test_unknown_criterion_id_in_evaluation_is_ignored():
    """An evaluation referring to a criterion id not in the rubric is ignored
    (defensive — shouldn't happen in practice but should not crash)."""
    criteria = [_crit_doc("PQC_DOC_PAN")]
    evals = [
        _ev("PQC_DOC_PAN", "PROVIDED"),
        _ev("PQC_DOC_NONEXISTENT", "NOT_PROVIDED"),
    ]
    verdict, _ = compute_overall_verdict("V", False, criteria, evals)
    assert verdict == "ACCEPTED"


def test_remarks_include_extracted_value_marker_when_threshold_failed():
    criteria = [_crit_technical_similar_work()]
    evals = [
        _ev(
            "PQC_TECH_SIMILAR_WORK",
            "VALUE",
            extracted_value=None,  # LLM didn't extract a value
            threshold_met=False,
        )
    ]
    _, remarks = compute_overall_verdict("V", False, criteria, evals)
    assert "(value not extracted)" in remarks
