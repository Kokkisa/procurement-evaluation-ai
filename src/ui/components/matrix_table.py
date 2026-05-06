"""HTML matrix renderer.

Builds a single ``<table class="proceval-matrix">`` shaped like a real PSU
technical evaluation: criteria as rows, vendors as columns, an OVERALL
REMARKS row at the bottom. Each per-(criterion, vendor) cell is colour-coded
by the LLM's verdict: green pass / red fail / yellow partial / grey N/A.
"""

from __future__ import annotations

import html
from typing import Any

import streamlit as st


def render_matrix(criteria: list[dict[str, Any]], vendor_evaluations: list[dict[str, Any]]) -> None:
    """Render an HTML matrix from the API's TechnicalEvaluation /
    CommercialEvaluation payload (already JSON-deserialised).

    ``criteria`` is the rubric's criterion list; ``vendor_evaluations`` is
    the per-vendor result list. Both come straight from the API response.
    """
    if not criteria:
        st.info("No criteria in this rubric.")
        return
    if not vendor_evaluations:
        st.info("No vendor evaluations to display.")
        return

    st.markdown(_build_html(criteria, vendor_evaluations), unsafe_allow_html=True)


def _build_html(criteria, vendor_evaluations) -> str:
    rows: list[str] = []

    # Header
    header_cells = [
        "<th>S.No.</th>",
        "<th>CRITERION</th>",
        "<th>REQUIREMENT</th>",
    ]
    for ve in vendor_evaluations:
        msme_badge = '<span class="msme-badge">MSME</span>' if ve.get("is_msme") else ""
        header_cells.append(f'<th class="vendor">{html.escape(ve["vendor_name"])}{msme_badge}</th>')
    rows.append("<thead><tr>" + "".join(header_cells) + "</tr></thead>")

    # Body rows
    body: list[str] = []
    for idx, criterion in enumerate(criteria, start=1):
        cells = [
            f'<td class="col-sno">{idx}</td>',
            f'<td class="col-criterion">{html.escape(criterion.get("name") or "")}</td>',
            f'<td class="col-requirement">{_format_requirement(criterion)}</td>',
        ]
        for ve in vendor_evaluations:
            cell_html, css_class = _format_cell_for(criterion, ve)
            cells.append(f'<td class="{css_class}">{cell_html}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")

    # OVERALL REMARKS row
    remarks_cells = ['<td colspan="3" class="col-criterion"><b>OVERALL REMARKS</b></td>']
    for ve in vendor_evaluations:
        verdict = (ve.get("overall_verdict") or "").upper()
        css = "cell-pass" if verdict == "ACCEPTED" else "cell-fail"
        remarks_cells.append(
            f'<td class="{css}">'
            f'<div class="verdict-tag {"pass" if verdict == "ACCEPTED" else "fail"}">{html.escape(verdict)}</div>'
            f"{html.escape(ve.get('overall_remarks') or '')}"
            f"</td>"
        )
    body.append('<tr class="overall-row">' + "".join(remarks_cells) + "</tr>")

    rows.append("<tbody>" + "".join(body) + "</tbody>")
    return f'<table class="proceval-matrix">{"".join(rows)}</table>'


def _format_requirement(criterion: dict[str, Any]) -> str:
    parts: list[str] = []
    threshold = criterion.get("threshold_value")
    msme = criterion.get("msme_relaxation_value")
    agg = criterion.get("aggregation_rule")
    if threshold is not None:
        chunk = f">= {threshold:.2f} L"
        if msme is not None:
            chunk += f" (MSME {msme:.2f} L)"
        if agg:
            chunk += f", {agg}"
        parts.append(chunk)
    src = criterion.get("source_clause")
    if src:
        parts.append(f"<br><small>{html.escape(src)}</small>")
    if not parts:
        return "<i>document submission</i>"
    return "".join(parts)


def _format_cell_for(criterion: dict[str, Any], vendor_eval: dict[str, Any]) -> tuple[str, str]:
    """Find this criterion's evaluation under this vendor and return (html, css_class)."""
    cell_eval = next(
        (
            e
            for e in vendor_eval.get("criterion_evaluations", [])
            if e.get("criterion_id") == criterion.get("id")
        ),
        None,
    )
    if cell_eval is None:
        return ("<i>no result</i>", "cell-na")

    verdict = (cell_eval.get("verdict") or "").upper()
    extracted = cell_eval.get("extracted_value")
    threshold_met = cell_eval.get("threshold_met")
    reasoning = cell_eval.get("reasoning") or ""
    short_reason = html.escape(reasoning[:120] + ("..." if len(reasoning) > 120 else ""))

    if verdict == "PROVIDED":
        return (
            f'<div class="verdict-tag pass">PROVIDED</div><small>{short_reason}</small>',
            "cell-pass",
        )
    if verdict == "NOT_PROVIDED":
        return (
            f'<div class="verdict-tag fail">NOT PROVIDED</div><small>{short_reason}</small>',
            "cell-fail",
        )
    if verdict == "VALUE":
        css = "cell-pass" if threshold_met else "cell-fail"
        tag_class = "pass" if threshold_met else "fail"
        value = html.escape(extracted or "(no value)")
        return (
            f'<div class="verdict-tag {tag_class}">{value}</div><small>{short_reason}</small>',
            css,
        )
    if verdict == "PARTIAL":
        return (
            f'<div class="verdict-tag partial">PARTIAL</div><small>{short_reason}</small>',
            "cell-partial",
        )
    return (
        f'<div class="verdict-tag partial">{html.escape(verdict)}</div><small>{short_reason}</small>',
        "cell-partial",
    )
