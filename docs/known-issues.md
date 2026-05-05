\# Known Issues — v0.1



\## Gold-standard verification mismatch (run\_eval\_test.py)



The E2E test script's gold-standard ACCEPT/REJECT comparison reports MISSING

for all vendors when the system actually produces correct verdicts in the

audit log and PDF. This is a verification-script bug, not an evaluation bug.



The script reads from a combined-verdict field that doesn't account for the

tech/commercial split. Vendors correctly evaluated as ACCEPTED on technical 

\+ REJECTED on commercial appear as MISSING in the comparison.



System correctness verified by:

\- PDF output (technical matrix shows correct ACCEPT/REJECT per vendor)

\- LangSmith trace tree (every criterion evaluation captured)

\- Audit log (5 lifecycle events recorded, verdicts persist correctly)



Planned fix: split gold-standard into tech\_expected / comm\_expected fields,

update comparison logic. Tracked as v0.2 cleanup.

