"""Shared evaluation pipeline used by /confirm and /review/reject.

Both endpoints execute the same chain — criteria extraction + per-vendor
evaluation against technical_criteria + commercial_criteria — but with
different feedback semantics. Factored here so the routes stay thin.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..agents import CriteriaExtractionAgent, VendorEvaluationAgent
from ..agents.evaluation_agent import load_vendor_documents
from ..ingestion import build_vendor_index, extract_text
from ..schemas.evaluation import CommercialEvaluation, TechnicalEvaluation
from ..schemas.tender import TenderMetadata
from ..schemas.vendor import VendorEvaluation


async def run_full_evaluation(
    tender_path: Path,
    vendors_root: Path,
    metadata: TenderMetadata,
    criteria_agent: CriteriaExtractionAgent,
    eval_agent: VendorEvaluationAgent,
    feedback_text: str | None = None,
) -> tuple[TechnicalEvaluation, CommercialEvaluation]:
    """Extract criteria, evaluate every vendor against both rubrics, return
    the assembled TechnicalEvaluation + CommercialEvaluation.

    ``feedback_text`` is plumbed through to the criteria agent only; the
    evaluation agent doesn't currently take a feedback param (extending it
    would be a Block 6.5 task — for now the criteria-extraction shift is
    where reviewer feedback bites first, and the new criteria propagate).
    """
    tender_text, _ = extract_text(tender_path)
    rubric = criteria_agent.extract(tender_text, metadata, feedback_text=feedback_text)

    vendor_dirs = sorted(p for p in vendors_root.iterdir() if p.is_dir())
    submissions = build_vendor_index(vendor_dirs)
    by_name = {s.vendor_name: s for s in submissions}

    tech_per_vendor: list[VendorEvaluation] = []
    comm_per_vendor: list[VendorEvaluation] = []

    for vendor_dir in vendor_dirs:
        sub = by_name.get(vendor_dir.name)
        if sub is None:
            continue
        # Per ADR-0007: load each vendor doc as its own VendorDocument so the
        # agent can fan out per (criterion, document) instead of stuffing the
        # whole vendor blob into a single prompt.
        documents = load_vendor_documents(vendor_dir)

        tech_eval, comm_eval = await asyncio.gather(
            eval_agent.aevaluate_vendor_full(
                rubric.technical_criteria,
                sub.vendor_name,
                sub.detected_msme,
                documents,
            ),
            eval_agent.aevaluate_vendor_full(
                rubric.commercial_criteria,
                sub.vendor_name,
                sub.detected_msme,
                documents,
            )
            if rubric.commercial_criteria
            else _empty_eval(sub.vendor_name, sub.detected_msme),
        )
        tech_per_vendor.append(tech_eval)
        comm_per_vendor.append(comm_eval)

    tech_aggregate = TechnicalEvaluation(
        rubric=rubric,
        vendor_evaluations=tech_per_vendor,
        qualified_count=sum(1 for e in tech_per_vendor if e.overall_verdict == "ACCEPTED"),
        total_count=len(tech_per_vendor),
        summary_remarks=(
            f"{sum(1 for e in tech_per_vendor if e.overall_verdict == 'ACCEPTED')} "
            f"of {len(tech_per_vendor)} participated vendors are technically qualified."
        ),
    )
    comm_aggregate = CommercialEvaluation(
        rubric=rubric,
        vendor_evaluations=comm_per_vendor,
        qualified_count=sum(1 for e in comm_per_vendor if e.overall_verdict == "ACCEPTED"),
        total_count=len(comm_per_vendor),
    )
    return tech_aggregate, comm_aggregate


async def _empty_eval(vendor_name: str, is_msme: bool) -> VendorEvaluation:
    return VendorEvaluation(
        vendor_name=vendor_name,
        is_msme=is_msme,
        criterion_evaluations=[],
        overall_verdict="ACCEPTED",
        overall_remarks="No commercial criteria defined for this tender.",
    )
