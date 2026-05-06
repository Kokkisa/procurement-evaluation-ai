# Loom Recording Script — Procurement Evaluation AI v0.1.0

7-minute walkthrough. Two columns: what to **say** + what's **on screen**. Recorded at v0.1.0 (commit on `main`, tag `v0.1.0`).

**Pre-recording checklist:**

- [ ] Repo open in editor at v0.1.0 (`git checkout v0.1.0`)
- [ ] Browser tabs ready: GitHub repo, LangSmith run for the validation evaluation, the rendered PDF
- [ ] Terminal open at repo root
- [ ] Camera + mic test (run a 10-second sample first; check audio level)
- [ ] Notifications silenced (Slack, mail, OS-level)
- [ ] Loom set to record screen + face cam (small overlay, bottom-right)

---

## Section 1 — Problem (1 min)

| Beat | Say | On screen |
|---|---|---|
| 1.0 — Hook (10s) | "Procurement evaluation in Indian PSUs is the kind of work where every ten years someone says 'we should just automate this.' Today I'll show you a system that actually does it, end-to-end, and that I just validated against real bid data this week." | Camera-only intro, project name visible in lower-third or window title |
| 1.1 — Problem (30s) | "A typical tender draws 7 to 70 vendors. Each submits roughly 10 PDFs — audited financials, GST certificates, similar-work POs, declarations. A procurement officer manually opens hundreds of PDFs, cross-checks each against the tender's pre-qualification criteria, computes thresholds with MSME relaxations, and types up the evaluation matrix. It takes 2-3 working days and it's audit-fragile — every error becomes a vendor dispute." | Static slide or whiteboard sketch: "10 vendors × 10 PDFs × ~10 criteria = 1000 cells, manual" |
| 1.2 — What this system does (20s) | "This system ingests the tender plus all vendor submissions, runs a multi-agent LLM pipeline to extract criteria and evaluate every vendor against every document, produces an audit-grade PDF that a Plant Manager can sign, and writes a full lifecycle audit log. Every state transition is recorded; every LLM call is traced." | Switch to repo README hero — show the architecture mermaid block |

## Section 2 — Architecture (1 min)

| Beat | Say | On screen |
|---|---|---|
| 2.0 — One-liner (15s) | "It's a FastAPI service backed by Postgres, with five lifecycle endpoints in strict order, an audit log on every transition, and LangSmith traces on every LLM call." | README "Architecture" mermaid diagram visible |
| 2.1 — Lifecycle (25s) | "Flow is: `/ingest` saves the upload and extracts metadata. `/confirm` runs criteria extraction plus per-vendor evaluation — that's the heavy LLM step. `/review/accept` or `/review/reject` is the human-in-the-loop gate; reject re-runs the chain with reviewer feedback. `/approve` generates the final PDF. `/push` archives the snapshot. There's also a read-only `/audit` endpoint." | Walk over the mermaid arrows with the cursor as you say each endpoint |
| 2.2 — Agents (20s) | "Three LLM agents: Metadata extraction is one call. Criteria extraction is one call against the tender. Vendor evaluation fans out per (vendor × criterion × document) — that's where most of the cost lives. Then a deterministic Python aggregator produces the final accept/reject. No LLM in the aggregation step; that's by design for auditability." | Open `src/proceval/agents/` in the editor; briefly highlight `metadata_agent.py`, `criteria_agent.py`, `evaluation_agent.py`, `verdict.py` in the file tree |

## Section 3 — Live demo (2 min)

This is the load-bearing section. The PDF is from the real-data run on 2026-05-06.

| Beat | Say | On screen |
|---|---|---|
| 3.0 — Open the PDF (15s) | "This is the PDF from a real run earlier this week — three vendors from a public-sector procurement tender, twenty-three documents, fifty percent of them notarised scans. About two hundred LLM calls. Total spend: fifty cents." | Open the generated PDF in a PDF reader; show page 1 — header band + tender metadata + vendor list |
| 3.1 — Tech matrix overview (20s) | "Page 2 is the technical evaluation matrix. Three vendor columns, nine criteria rows, color-coded cells. Green is satisfied. Red is not. The bottom row is OVERALL REMARKS — the system's per-vendor accept/reject summary." | Scroll to the technical matrix page; cursor across the column headers; pause on the OVERALL REMARKS row |
| 3.2 — Walk a rejected vendor (45s) | "Walk through one of the rejected vendors with me — call it Vendor B. Most criteria green — turnover threshold met, similar works met, GST, Udyam, declarations all present. Then look at the PAN row — red, NOT_PROVIDED. The reasoning column says specifically: no PAN card found in the submitted documents, and the bidder response form lists PAN but doesn't attach the certificate. That single missing document drives the REJECTED verdict in OVERALL REMARKS. I cross-checked this against the human evaluator's decision sheet — same outcome." | Zoom or highlight one rejected-vendor column; pause on the PAN cell, then on the OVERALL REMARKS cell at the bottom |
| 3.3 — The self-attested catch (30s) | "Here's the part I want to flag. On one of the PAN cells, the system noted that the document was present but **not** self-attested. The tender's PQC clause says 'self-attested copy of PAN.' A human reviewer manually flipping through 23 PDFs typically catches the missing-document case but misses the present-but-not-self-attested case. The LLM caught both. This is the kind of finding that an audit team raises six months later. The system surfaced it on day one." | Highlight the specific reasoning text; if needed, switch to the corresponding LangSmith trace span to show the same reasoning string |
| 3.4 — Audit appendix (10s) | "Page 4 is the lifecycle audit log — every state transition, who triggered it, when, what notes. This is the document the approver signs at the bottom." | Scroll to the audit log page; show the chronological table |

## Section 4 — Engineering decisions (1.5 min)

| Beat | Say | On screen |
|---|---|---|
| 4.0 — How we got here (20s) | "The interesting engineering wasn't 'build the agents.' Three problems showed up only when we tried real data, and the architecture changed each time." | Open `docs/adr/` in the editor — show ADR-0001 through ADR-0008 in the file tree |
| 4.1 — ADR-0006 hybrid OCR (30s) | "First problem. Synthetic test fixtures are clean digital PDFs; real bid packs are 50% scanned notarised certificates. pdfplumber returns empty strings on those. Block 13 added a hybrid extractor: text-layer first, Tesseract OCR fallback per page when the text layer comes back below a threshold. Configurable, traceable, doesn't impose Tesseract as a hard dependency on people who only process digital docs." | Open ADR-0006; scroll to the "Why hybrid not always-OCR" section |
| 4.2 — ADR-0007 per-document fan-out (40s) | "Second problem, way more interesting. Block 14. Real-data run hit `context_length_exceeded` — one vendor's concatenated text was 139,000 tokens against gpt-4o-mini's 128k ceiling. We were stuffing the whole vendor blob into one prompt. Block 14 reshapes the call: one LLM call per (vendor, criterion, document) tuple, then deterministic Python aggregation. 'Any MEETS wins; else strongest DOES_NOT_MEET cited; else NOT_APPLICABLE.' Bounds per-call payload by construction. Per-document reasoning visible in LangSmith. Auditability matches the procurement domain reality — when you reject a vendor, you can point at the document that did it." | Open ADR-0007; pause on the validation criteria block |
| 4.3 — Why deterministic aggregation (20s) | "Worth one beat on the design. The aggregation logic is intentionally not an LLM call. It's pure Python, in `verdict.py` and `aggregate_document_verdicts`. Rules are inspectable, deterministic, and produce identical output for identical input — which is the property a procurement audit team requires. The LLM does the per-document reasoning; the rule engine does the roll-up." | Open `src/proceval/agents/verdict.py` and `evaluation_agent.py::aggregate_document_verdicts`; cursor across the if/elif chain |

## Section 5 — Honest limitations (1 min)

| Beat | Say | On screen |
|---|---|---|
| 5.0 — Three issues (15s) | "I tagged v0.1.0 today. Three rough edges that are documented in ADR-0008 and will land as 15.1, 15.2, 15.3." | Open `docs/adr/ADR-0008-known-issues-v0.1.0.md` |
| 5.1 — VerdictPerDoc enum leak (20s) | "First: on document-existence criteria where the document body carries an identifier — Udyam number, GSTIN — the matrix cell renders as VALUE instead of PROVIDED. Cosmetic; the accept/reject decision is unaffected. One-line fix in the aggregator." | Highlight Issue 15.1 in ADR-0008 |
| 5.2 — PDF filename collision (15s) | "Second: the generated PDF filename doesn't include the `eval_id` prefix. Two concurrent evaluations of the same tender would clobber each other in `data/outputs/`. Single-deployment doesn't hit this; multi-tenant would. Block 15.2 adds the prefix." | Highlight Issue 15.2 |
| 5.3 — PowerShell ergonomics (10s) | "Third: PowerShell aliases `curl` to `Invoke-WebRequest`, so the README's `curl` examples returned 422 from Windows. Block 15.3 — already in v0.1.0 — added an `Invoke-RestMethod` section to the README." | Switch to README; show the new "Calling the API from Windows PowerShell" section |

## Section 6 — Wrap (30s)

| Beat | Say | On screen |
|---|---|---|
| 6.0 — Where to find it (15s) | "Repo is on GitHub at `Kokkisa/procurement-evaluation-ai`. Tagged `v0.1.0`. Tech stack: Python 3.11, FastAPI, Postgres, LangChain, ReportLab, OpenAI or Anthropic or Ollama via a provider-agnostic factory. Eight ADRs documenting the design decisions." | GitHub repo page, tag list visible |
| 6.1 — Contact (15s) | "If you want to talk about this — procurement automation, multi-agent systems, the trade-offs in ADR-0007 — I'm happy to chat. Email or LinkedIn in the description below." | Camera-only outro; consider name + contact card overlay |

---

## Time budget

| Section | Target | Cumulative |
|---|---|---|
| 1. Problem | 1:00 | 1:00 |
| 2. Architecture | 1:00 | 2:00 |
| 3. Live demo | 2:00 | 4:00 |
| 4. Engineering decisions | 1:30 | 5:30 |
| 5. Honest limitations | 1:00 | 6:30 |
| 6. Wrap | 0:30 | 7:00 |

If a beat runs long, drop the optional content first: the LangSmith trace cross-reference in 3.3, the rule-engine deep dive in 4.3.

## Recording tips

- Slow down on Section 3.2 (rejected-vendor walk-through) and 3.3 (self-attested catch). Those are the two beats viewers will remember.
- The ADR-0007 explanation in 4.2 is the most technically dense; rehearse it once before recording.
- Keep the cursor visible and move it where you're talking. Highlighting beats narration.
- Pause briefly between sections so the editor (or you) can cut transitions.
- Loom auto-trims silences > 2 seconds when you enable that option in settings — useful for hesitations.
