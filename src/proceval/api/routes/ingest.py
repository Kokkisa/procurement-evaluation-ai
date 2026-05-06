"""POST /ingest — upload tender + vendor archives, extract metadata.

Saves files under ``settings.upload_dir/{eval_id}/{tender.pdf, vendors/...}``,
runs MetadataExtractionAgent on the tender PDF, builds the vendor index from
disk, persists an Evaluation row in status ``metadata_extracted``, and
returns the 2-tab confirmation payload (tender meta + vendor list).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ...agents import MetadataExtractionAgent
from ...audit import log_event
from ...config import settings
from ...db.models import Document, Evaluation
from ...ingestion import build_vendor_index, extract_text, unzip_to_directory
from ...schemas.audit import ActorRole, AuditAction
from ..deps import get_db, get_metadata_agent
from ..schemas import IngestResponse
from ..state import EvalStatus

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    actor_id: str = Form(...),
    tender: UploadFile = File(...),
    vendor_files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    metadata_agent: MetadataExtractionAgent = Depends(get_metadata_agent),
) -> IngestResponse:
    if not vendor_files:
        raise HTTPException(status_code=400, detail="At least one vendor file is required.")

    eval_id = uuid4()
    eval_root = Path(settings.upload_dir) / str(eval_id)
    tender_path = eval_root / "tender.pdf"
    vendors_root = eval_root / "vendors"
    eval_root.mkdir(parents=True, exist_ok=True)
    vendors_root.mkdir(parents=True, exist_ok=True)

    # Save tender PDF
    if not (tender.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Tender file must be a PDF.")
    _save_upload(tender, tender_path)

    # Save vendor files (zip -> unzip into a per-vendor folder; pdf -> single-vendor folder)
    for vf in vendor_files:
        name = vf.filename or "vendor"
        stem = Path(name).stem.strip().replace(" ", "_") or "vendor"
        vendor_dir = vendors_root / stem
        vendor_dir.mkdir(parents=True, exist_ok=True)
        if name.lower().endswith(".zip"):
            tmp_zip = vendor_dir / "_archive.zip"
            _save_upload(vf, tmp_zip)
            unzip_to_directory(tmp_zip, vendor_dir)
            tmp_zip.unlink(missing_ok=True)
        elif name.lower().endswith(".pdf"):
            _save_upload(vf, vendor_dir / Path(name).name)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Vendor upload {name!r} must be .zip or .pdf",
            )

    # Parse tender + run metadata extraction
    tender_text, tender_pages = extract_text(tender_path)
    metadata = metadata_agent.extract(tender_text)

    # Build vendor index from disk
    vendor_dirs = sorted(p for p in vendors_root.iterdir() if p.is_dir())
    vendors = build_vendor_index(vendor_dirs)

    # Persist
    ev = Evaluation(
        id=eval_id,
        tender_number=metadata.tender_number,
        tender_name=metadata.tender_name,
        tender_floated_date=metadata.tender_floated_date,
        tender_due_date=metadata.tender_due_date,
        tender_metadata_json=metadata.model_dump(mode="json"),
        status=EvalStatus.METADATA_EXTRACTED,
        preparer_id=actor_id,
        iteration=1,
    )
    db.add(ev)
    db.flush()

    # Track docs for the audit trail / archive snapshot
    db.add(
        Document(
            evaluation_id=eval_id,
            vendor_name=None,
            document_type="tender",
            file_path=str(tender_path),
            page_count=tender_pages,
        )
    )
    for vs in vendors:
        for p in vs.document_paths:
            db.add(
                Document(
                    evaluation_id=eval_id,
                    vendor_name=vs.vendor_name,
                    document_type="vendor_submission",
                    file_path=p,
                )
            )

    log_event(
        db,
        evaluation_id=eval_id,
        action=AuditAction.UPLOADED,
        actor_id=actor_id,
        actor_role=ActorRole.PREPARER,
        notes=f"tender pdf + {len(vendors)} vendor folder(s)",
    )
    log_event(
        db,
        evaluation_id=eval_id,
        action=AuditAction.METADATA_EXTRACTED,
        actor_id=actor_id,
        actor_role=ActorRole.SYSTEM,
        notes=f"tender_number={metadata.tender_number}",
    )

    db.commit()

    return IngestResponse(eval_id=eval_id, metadata=metadata, vendors=vendors)


def _save_upload(upload: UploadFile, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
