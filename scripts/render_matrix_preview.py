"""Render the evaluation matrix to a standalone HTML file using synthetic data.

Lets us eyeball the matrix renderer without spinning up Streamlit + FastAPI +
hitting the LLM. Output: ``data/outputs/matrix_preview.html``.
"""

from __future__ import annotations

from pathlib import Path

from ui.components.matrix_table import _build_html
from ui.styles import CSS

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "data" / "outputs" / "matrix_preview.html"


CRITERIA = [
    {
        "id": "PQC_FIN_TURNOVER",
        "name": "Average Annual Turnover",
        "type": "financial",
        "threshold_value": 100.0,
        "msme_relaxation_value": 85.0,
        "aggregation_rule": "average",
        "source_clause": "PQC-1 (Financial)",
    },
    {
        "id": "PQC_TECH_SIMILAR_WORK",
        "name": "Similar Works Experience",
        "type": "technical",
        "threshold_value": 100.0,
        "msme_relaxation_value": 85.0,
        "aggregation_rule": "single_max",
        "source_clause": "PQC-2 (Technical)",
    },
    {"id": "PQC_DOC_PAN", "name": "PAN Card Submission", "type": "document", "source_clause": "PQC-3"},
    {"id": "PQC_DOC_GST", "name": "GST Registration", "type": "document", "source_clause": "PQC-4"},
    {"id": "PQC_DOC_UDYAM_MSME", "name": "Udyam Registration", "type": "document", "source_clause": "PQC-5"},
    {"id": "PQC_DOC_BLACKLIST_DECL", "name": "Blacklisting Declaration", "type": "document", "source_clause": "PQC-6"},
    {"id": "PQC_DOC_BIDDER_RESPONSE", "name": "Bidder Response Form", "type": "document", "source_clause": "PQC-7"},
]


def _ev(cid, verdict, value=None, met=None, reason="evidence found"):
    return {
        "criterion_id": cid,
        "verdict": verdict,
        "extracted_value": value,
        "threshold_met": met,
        "reasoning": reason,
        "confidence": 0.95,
    }


def _vendor(name, msme, accept, evals, remarks):
    return {
        "vendor_name": name,
        "is_msme": msme,
        "criterion_evaluations": evals,
        "overall_verdict": "ACCEPTED" if accept else "REJECTED",
        "overall_remarks": remarks,
    }


VENDORS = [
    _vendor(
        "AROHA FACILITY SERVICES PVT LTD", True, True,
        [
            _ev("PQC_FIN_TURNOVER", "VALUE", "88.23 LAKHS (3-yr avg, MSME)", True, "Computed from FY 23-24/22-23/21-22 audited B/S"),
            _ev("PQC_TECH_SIMILAR_WORK", "VALUE", "118.50 LAKHS", True, "Single PO with MERIDIAN MANUFACTURING"),
            _ev("PQC_DOC_PAN", "PROVIDED", reason="pan_card.pdf present"),
            _ev("PQC_DOC_GST", "PROVIDED", reason="GST REG-06 enclosed"),
            _ev("PQC_DOC_UDYAM_MSME", "PROVIDED", reason="udyam_registration.pdf present"),
            _ev("PQC_DOC_BLACKLIST_DECL", "PROVIDED", reason="Letterhead declaration enclosed"),
            _ev("PQC_DOC_BIDDER_RESPONSE", "PROVIDED", reason="Form signed and submitted"),
        ],
        "All 7 evaluated criteria are satisfied. Vendor is technically qualified.",
    ),
    _vendor(
        "TEJASWINI HOUSEKEEPING ENTERPRISES", False, True,
        [
            _ev("PQC_FIN_TURNOVER", "VALUE", "238.67 LAKHS (3-yr avg)", True),
            _ev("PQC_TECH_SIMILAR_WORK", "VALUE", "164.20 LAKHS", True),
            _ev("PQC_DOC_PAN", "PROVIDED"),
            _ev("PQC_DOC_GST", "PROVIDED"),
            _ev("PQC_DOC_UDYAM_MSME", "PROVIDED", reason="N/A (non-MSME, no relaxation claimed)"),
            _ev("PQC_DOC_BLACKLIST_DECL", "PROVIDED"),
            _ev("PQC_DOC_BIDDER_RESPONSE", "PROVIDED"),
        ],
        "All 7 evaluated criteria are satisfied. Vendor is technically qualified.",
    ),
    _vendor(
        "SHRI MANGALAM SAFAI WORKS", True, False,
        [
            _ev("PQC_FIN_TURNOVER", "VALUE", "92.70 LAKHS (3-yr avg, MSME)", True),
            _ev("PQC_TECH_SIMILAR_WORK", "VALUE", "38.42 LAKHS", False, "Single PO with ARYA PACKAGING - below 85L MSME-relaxed threshold"),
            _ev("PQC_DOC_PAN", "PROVIDED"),
            _ev("PQC_DOC_GST", "PROVIDED"),
            _ev("PQC_DOC_UDYAM_MSME", "PROVIDED"),
            _ev("PQC_DOC_BLACKLIST_DECL", "PROVIDED"),
            _ev("PQC_DOC_BIDDER_RESPONSE", "PROVIDED"),
        ],
        "Vendor did not meet Similar Works Experience threshold of 85.00 Lakhs (MSME-relaxed) - provided value 38.42 LAKHS. Hence rejected.",
    ),
    _vendor(
        "PRABHAT DEEP SANITATION SOLUTIONS", False, True,
        [
            _ev("PQC_FIN_TURNOVER", "VALUE", "215.60 LAKHS (3-yr avg)", True),
            _ev("PQC_TECH_SIMILAR_WORK", "VALUE", "192.70 LAKHS", True),
            _ev("PQC_DOC_PAN", "PROVIDED"),
            _ev("PQC_DOC_GST", "PROVIDED"),
            _ev("PQC_DOC_UDYAM_MSME", "PROVIDED", reason="N/A (non-MSME)"),
            _ev("PQC_DOC_BLACKLIST_DECL", "PROVIDED"),
            _ev("PQC_DOC_BIDDER_RESPONSE", "PROVIDED"),
        ],
        "All 7 evaluated criteria are satisfied. Vendor is technically qualified.",
    ),
    _vendor(
        "RAGHAVENDRA MAINTENANCE WORKS", False, False,
        [
            _ev("PQC_FIN_TURNOVER", "VALUE", "1090.17 LAKHS (3-yr avg)", True),
            _ev("PQC_TECH_SIMILAR_WORK", "VALUE", "211.40 LAKHS", True),
            _ev("PQC_DOC_PAN", "PROVIDED"),
            _ev("PQC_DOC_GST", "PROVIDED"),
            _ev("PQC_DOC_UDYAM_MSME", "PROVIDED", reason="N/A (non-MSME)"),
            _ev("PQC_DOC_BLACKLIST_DECL", "NOT_PROVIDED", reason="No blacklisting declaration found in submission folder"),
            _ev("PQC_DOC_BIDDER_RESPONSE", "PROVIDED"),
        ],
        "Vendor did not provide Blacklisting Declaration. Hence rejected.",
    ),
]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    table_html = _build_html(CRITERIA, VENDORS)
    full = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Evaluation Matrix Preview</title>
{CSS}
<style>
body {{ background:#fafafa; font-family:'Segoe UI', sans-serif; padding:24px; color:#222; }}
h1 {{ margin:0 0 4px 0; font-size:20px; }}
.meta {{ color:#555; margin-bottom:18px; font-size:13px; }}
</style>
</head>
<body>
<h1>Procurement Evaluation Matrix - Preview</h1>
<div class="meta">
  Tender: <code>DEMO/2026/HKP/001</code> | Iteration: 1 | Status: <code>eval_ready</code><br>
  Synthetic data — same shape as the live API's TechnicalEvaluation payload.
</div>
{table_html}
</body>
</html>
"""
    OUT.write_text(full, encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
