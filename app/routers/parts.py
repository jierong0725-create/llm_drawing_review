import os
import tempfile
import threading
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..models import (
    Part, Version, Drawing, Dimension,
    ProcessingStatus, ConfirmResult, DimensionSource, DimensionType,
)
from ..services.extractor import extract_from_pdf
from ..services.vision import vision_check
from ..services.reconciler import reconcile

router = APIRouter(prefix="/parts", tags=["parts"])
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "../templates"))


@router.get("/", response_class=HTMLResponse)
def list_parts(request: Request, db: Session = Depends(get_db)):
    parts = db.query(Part).order_by(Part.created_at.desc()).all()
    return templates.TemplateResponse("parts/list.html", {"request": request, "parts": parts})


@router.post("/", response_class=HTMLResponse)
def create_part(
    request: Request,
    name: str = Form(...),
    drawing_number: str = Form(...),
    db: Session = Depends(get_db),
):
    existing = db.query(Part).filter(Part.drawing_number == drawing_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="图号已存在")
    part = Part(name=name, drawing_number=drawing_number)
    db.add(part)
    db.commit()
    db.refresh(part)
    parts = db.query(Part).order_by(Part.created_at.desc()).all()
    return templates.TemplateResponse("parts/list.html", {"request": request, "parts": parts})


@router.get("/{part_id}", response_class=HTMLResponse)
def part_detail(request: Request, part_id: int, db: Session = Depends(get_db)):
    part = db.query(Part).filter(Part.id == part_id).first()
    if not part:
        raise HTTPException(status_code=404, detail="零件不存在")
    return templates.TemplateResponse("parts/detail.html", {"request": request, "part": part})


@router.post("/{part_id}/versions", response_class=HTMLResponse)
def create_version(
    request: Request,
    part_id: int,
    version_code: str = Form(...),
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    part = db.query(Part).filter(Part.id == part_id).first()
    if not part:
        raise HTTPException(status_code=404, detail="零件不存在")

    db.query(Version).filter(Version.part_id == part_id).update({"is_current": False})

    version = Version(
        part_id=part_id,
        version_code=version_code,
        is_current=True,
        status=ProcessingStatus.processing,
    )
    db.add(version)
    db.flush()

    # Save uploaded files to temp dir; keep (drawing_id, path) pairs for background task
    tmp_dir = tempfile.mkdtemp()
    drawing_paths: list[tuple[int, str]] = []

    for i, upload in enumerate(files, start=1):
        drawing = Drawing(version_id=version.id, sequence=i, filename=upload.filename)
        db.add(drawing)
        db.flush()

        tmp_path = os.path.join(tmp_dir, f"{drawing.id}_{upload.filename}")
        with open(tmp_path, "wb") as f:
            f.write(upload.file.read())
        drawing_paths.append((drawing.id, tmp_path))

    db.commit()
    version_id = version.id

    # Run processing in background so the HTTP response returns immediately
    thread = threading.Thread(
        target=_process_version,
        args=(version_id, drawing_paths),
        daemon=True,
    )
    thread.start()

    db.refresh(part)
    return templates.TemplateResponse(
        "parts/detail.html", {"request": request, "part": part}
    )


def _process_version(version_id: int, drawing_paths: list[tuple[int, str]]) -> None:
    """Background task: extract dimensions, persist to DB, update status."""
    db: Session = SessionLocal()
    try:
        for drawing_id, pdf_path in drawing_paths:
            try:
                program_dims = extract_from_pdf(pdf_path)
                llm_dims = vision_check(pdf_path)
                final_dims = reconcile(program_dims, llm_dims)

                for seq, dim in enumerate(final_dims, start=1):
                    record = Dimension(
                        drawing_id=drawing_id,
                        sequence=seq,
                        value=dim.value,
                        nominal=dim.nominal,
                        tolerance=dim.tolerance,
                        dim_type=DimensionType(dim.dim_type),
                        view_name=dim.view_name,
                        source=DimensionSource(dim.source),
                        anchor_x=dim.anchor_x,
                        anchor_y=dim.anchor_y,
                    )
                    db.add(record)
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                # Clean up temp file
                try:
                    os.remove(pdf_path)
                except OSError:
                    pass

        version = db.query(Version).filter(Version.id == version_id).first()
        if version:
            version.status = ProcessingStatus.ready
            db.commit()
    except Exception as exc:
        # Mark version as failed (reuse pending to signal error without new enum value)
        try:
            version = db.query(Version).filter(Version.id == version_id).first()
            if version:
                version.status = ProcessingStatus.pending
                version.notes = f"处理失败: {exc}"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.post("/{part_id}/versions/{version_id}/confirm", response_class=HTMLResponse)
def confirm_version(
    request: Request,
    part_id: int,
    version_id: int,
    result: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    version = db.query(Version).filter(
        Version.id == version_id, Version.part_id == part_id
    ).first()
    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")

    version.confirm_result = ConfirmResult(result)
    version.status = ProcessingStatus.confirmed
    version.notes = notes
    version.confirmed_at = datetime.utcnow()
    db.commit()

    part = db.query(Part).filter(Part.id == part_id).first()
    return templates.TemplateResponse("parts/detail.html", {"request": request, "part": part})
