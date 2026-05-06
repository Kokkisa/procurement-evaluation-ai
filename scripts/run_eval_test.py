"""End-to-end integration runner — the 'single command to demo the system'.

Walks the full lifecycle against the synthetic vendors:
    POST /ingest               (upload tender + 5 vendor zips)
    POST /confirm/{eval_id}    (criteria extraction + per-vendor evaluation)
    GET  /audit/{eval_id}      (verify lifecycle events)
    POST /review/{eval_id}/accept
    POST /approve/{eval_id}    (final PDF)

Asserts the gold-standard ACCEPT/REJECT split lands in the final state for
all 5 vendors and prints a summary block (eval_id, iteration, per-vendor
verdict, PDF path, LangSmith project link).

Uses FastAPI's TestClient in-process — no separate uvicorn needed. The
DB is a real Postgres (transactional rollback would defeat /push); each
run leaves an eval row + audit-log + archive snapshot for inspection.

Usage:
    python scripts/run_eval_test.py

Requires ANTHROPIC_API_KEY in env / .env. Exits 1 on any assertion or
infrastructure failure (fail-fast).
"""

from __future__ import annotations

import io
import logging
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

# Surface evaluation-agent throttling lines ("Acquired LLM slot 2/3",
# "Sleeping 1.50s before batch 4") so the operator sees rate-limit
# decisions in real time. Silence noisier transport loggers.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
for _noisy in ("httpx", "httpcore", "urllib3", "openai", "anthropic", "langsmith"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

REPO_ROOT = Path(__file__).resolve().parent.parent
TENDER_PDF = REPO_ROOT / "tests" / "fixtures" / "tender_housekeeping_demo.pdf"
VENDORS_DIR = REPO_ROOT / "tests" / "fixtures" / "synthetic_vendors"

EXPECTED_VERDICTS = {
    "AROHA FACILITY SERVICES PVT LTD": "ACCEPTED",
    "TEJASWINI HOUSEKEEPING ENTERPRISES": "ACCEPTED",
    "SHRI MANGALAM SAFAI WORKS": "REJECTED",
    "PRABHAT DEEP SANITATION SOLUTIONS": "ACCEPTED",
    "RAGHAVENDRA MAINTENANCE WORKS": "REJECTED",
}


def _fail(msg: str) -> None:
    print(f"\nFAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _build_vendor_zip(vendor_dir: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for pdf in sorted(vendor_dir.glob("*.pdf")):
            zf.writestr(pdf.name, pdf.read_bytes())
    return buf.getvalue()


def main() -> dict[str, Any]:
    # Pre-flight: API key required, fail fast with a clear message
    from proceval.config import settings

    if not settings.anthropic_api_key:
        _fail(
            "ANTHROPIC_API_KEY missing — set it in .env or env. The E2E run "
            "needs a real key (CriteriaExtractionAgent + VendorEvaluationAgent "
            "make live LLM calls)."
        )

    # Imports deferred until after the pre-flight so the failure is fast
    from fastapi.testclient import TestClient

    from proceval.api.main import app

    client = TestClient(app)

    print("=" * 70)
    print("  Procurement Evaluation AI — E2E Integration Run")
    print("=" * 70)
    print(f"  Tender:  {TENDER_PDF.name}")
    vendor_dirs = sorted(p for p in VENDORS_DIR.iterdir() if p.is_dir())
    print(f"  Vendors: {len(vendor_dirs)} ({', '.join(p.name for p in vendor_dirs)})")
    print(f"  LLM:     {settings.anthropic_model} via provider={settings.llm_provider}")
    print(f"  Tracing: LANGCHAIN_TRACING_V2={settings.langchain_tracing_v2}")
    print()

    # 1. /ingest
    print("[1/5] POST /ingest ...")
    files = [("tender", (TENDER_PDF.name, TENDER_PDF.read_bytes(), "application/pdf"))]
    for vdir in vendor_dirs:
        files.append(
            ("vendor_files", (f"{vdir.name}.zip", _build_vendor_zip(vdir), "application/zip"))
        )
    t0 = time.time()
    r = client.post("/ingest", data={"actor_id": "preparer1"}, files=files)
    if r.status_code != 200:
        _fail(f"/ingest {r.status_code}: {r.text}")
    ingest = r.json()
    eval_id = ingest["eval_id"]
    print(f"      eval_id           = {eval_id}")
    print(f"      tender_number     = {ingest['metadata']['tender_number']}")
    msme_count = sum(1 for v in ingest["vendors"] if v["detected_msme"])
    print(f"      vendors detected  = {len(ingest['vendors'])} ({msme_count} MSME)")
    print(f"      elapsed           = {time.time() - t0:.1f}s")
    print()

    # 2. /confirm — fans out the LLM calls
    print("[2/5] POST /confirm/{eval_id} (criteria + per-vendor evaluation; ~2 min)...")
    t0 = time.time()
    r = client.post(f"/confirm/{eval_id}", json={"actor_id": "preparer1"})
    if r.status_code != 200:
        _fail(f"/confirm {r.status_code}: {r.text}")
    confirm = r.json()
    tech = confirm["technical"]
    comm = confirm["commercial"]
    print(f"      iteration                    = {confirm['iteration']}")
    print(f"      technical qualified          = {tech['qualified_count']}/{tech['total_count']}")
    print(f"      commercial qualified         = {comm['qualified_count']}/{comm['total_count']}")
    print(f"      elapsed                      = {time.time() - t0:.1f}s")
    print()

    # 3. /audit
    print("[3/5] GET  /audit/{eval_id} (verify lifecycle events) ...")
    r = client.get(f"/audit/{eval_id}")
    if r.status_code != 200:
        _fail(f"/audit {r.status_code}: {r.text}")
    audit = r.json()
    actions = [e["action"] for e in audit["events"]]
    expected_subset = (
        "uploaded",
        "metadata_extracted",
        "metadata_confirmed",
        "evaluation_generated",
        "sent_for_review",
    )
    missing = [a for a in expected_subset if a not in actions]
    if missing:
        _fail(f"audit log missing actions {missing}; got {actions}")
    print(f"      events recorded   = {len(audit['events'])}")
    print(f"      action sequence   = {' -> '.join(actions)}")
    print()

    # 4. /review/accept
    print("[4/5] POST /review/{eval_id}/accept ...")
    r = client.post(f"/review/{eval_id}/accept", json={"actor_id": "reviewer1"})
    if r.status_code != 200:
        _fail(f"/review/accept {r.status_code}: {r.text}")
    print(f"      status            = {r.json()['status']}")
    print()

    # 5. /approve
    print("[5/5] POST /approve/{eval_id} ...")
    r = client.post(f"/approve/{eval_id}", json={"actor_id": "approver1"})
    if r.status_code != 200:
        _fail(f"/approve {r.status_code}: {r.text}")
    approve = r.json()
    pdf_path = Path(approve["pdf_path"])
    print(f"      pdf_path          = {pdf_path}")
    print(
        f"      pdf size          = "
        f"{pdf_path.stat().st_size if pdf_path.exists() else 'MISSING'} bytes"
    )
    print()

    # Gold-standard assertion
    print("=" * 70)
    print("  GOLD-STANDARD ACCEPT/REJECT SPLIT")
    print("=" * 70)
    actual = {ve["vendor_name"]: ve["overall_verdict"] for ve in tech["vendor_evaluations"]}
    failures: list[str] = []
    for vname, expected in EXPECTED_VERDICTS.items():
        got = actual.get(vname, "MISSING")
        marker = "OK" if got == expected else "!!"
        msme_tag = (
            " (MSME)"
            if any(
                ve["vendor_name"] == vname and ve["is_msme"] for ve in tech["vendor_evaluations"]
            )
            else ""
        )
        print(f"  [{marker}] {vname:<40}{msme_tag:<8} -> {got:<10} (expected {expected})")
        if got != expected:
            failures.append(f"{vname}: expected {expected}, got {got}")
    print()
    if failures:
        _fail("Gold-standard split mismatch:\n  " + "\n  ".join(failures))

    # LangSmith link
    print("=" * 70)
    if settings.langchain_tracing_v2:
        project_url = f"https://smith.langchain.com/o/me/projects/p/{settings.langchain_project}"
        print(f"  LangSmith trace project: {project_url}")
        print(
            f"  Filter by start_time around now to see this run's "
            f"~{tech['total_count'] * 2 + 2}+ traces."
        )
    else:
        print("  LangSmith tracing disabled (LANGCHAIN_TRACING_V2=false).")
        print("  Set true in .env to capture token usage + child runs in the dashboard.")
    print("=" * 70)
    print()
    print("E2E PASS")

    return {
        "eval_id": eval_id,
        "iteration": confirm["iteration"],
        "verdicts": actual,
        "pdf_path": str(pdf_path),
        "audit_event_count": len(audit["events"]),
        "tracing_enabled": settings.langchain_tracing_v2,
    }


if __name__ == "__main__":
    main()
