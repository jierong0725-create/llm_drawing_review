import os
import threading
from collections import defaultdict
from datetime import datetime
from typing import List

import pdfplumber

from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..models import (
    Part, Version, Drawing, Dimension,
    ProcessingStatus, ConfirmResult, DimensionSource, DimensionType,
)
from ..services.extractor import extract_from_pdf, filter_by_views, filter_excluded
from ..services.vision import vision_check
from ..services.reconciler import reconcile
from ..services.analyzer import detect_excluded_regions, extract_dimensions_tiled
from ..services.image_gen import generate_drawing_images, RASTER_DPI

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "drawings")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "uploads")

router = APIRouter(prefix="/parts", tags=["parts"])
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "../templates"))


def _get_current_version_info(part):
    """Helper: return current version status info for a part."""
    current = next((v for v in part.versions if v.is_current), None)
    if not current:
        return None
    return {
        "id": current.id,
        "version_code": current.version_code,
        "status": current.status.value,
        "confirm_result": current.confirm_result.value if current.confirm_result else None,
    }

def _get_pending_count(part):
    """Helper: count pending dimensions across all drawings."""
    count = 0
    for version in part.versions:
        for drawing in version.drawings:
            count += sum(1 for d in drawing.dimensions if d.review_status and d.review_status.value == "pending")
    return count

def _get_total_dimension_count(part):
    """Helper: total dimension count across all drawings."""
    count = 0
    for version in part.versions:
        for drawing in version.drawings:
            count += len(drawing.dimensions)
    return count


@router.get("/", response_class=HTMLResponse)
def list_parts(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "parts_list.html", {"title": "零件列表"})


@router.get("/api/list")
def list_parts_json(db: Session = Depends(get_db)):
    parts = db.query(Part).order_by(Part.created_at.desc()).all()
    return [{
        "id": p.id, "name": p.name, "drawing_number": p.drawing_number,
        "current_version": _get_current_version_info(p),
        "pending_count": _get_pending_count(p),
        "total_count": _get_total_dimension_count(p),
        "created_at": p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else None,
    } for p in parts]


@router.post("/api/create")
def create_part_json(
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
    return JSONResponse({
        "id": part.id, "name": part.name, "drawing_number": part.drawing_number,
    }, status_code=201)


@router.get("/new", response_class=HTMLResponse)
def new_part_page(request: Request):
    return templates.TemplateResponse(request, "part_detail.html", {"title": "新增零件"})


@router.get("/api/{part_id}")
def part_detail_json(part_id: int, db: Session = Depends(get_db)):
    part = db.query(Part).filter(Part.id == part_id).first()
    if not part:
        raise HTTPException(status_code=404)
    return {
        "id": part.id, "name": part.name, "drawing_number": part.drawing_number,
        "current_version": _get_current_version_info(part),
        "created_at": part.created_at.strftime("%Y-%m-%d %H:%M") if part.created_at else None,
    }


@router.get("/{part_id}", response_class=HTMLResponse)
def part_detail(request: Request, part_id: int, db: Session = Depends(get_db)):
    part = db.query(Part).filter(Part.id == part_id).first()
    if not part:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "part_detail.html", {
        "title": f"{part.name} — 零件详情",
    })


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

    # Save uploaded files persistently for potential reprocessing
    upload_dir = os.path.join(UPLOAD_DIR, str(version.id))
    os.makedirs(upload_dir, exist_ok=True)
    drawing_paths: list[tuple[int, str]] = []

    for i, upload in enumerate(files, start=1):
        drawing = Drawing(version_id=version.id, sequence=i, filename=upload.filename)
        db.add(drawing)
        db.flush()

        saved_path = os.path.join(upload_dir, f"{drawing.id}_{upload.filename}")
        with open(saved_path, "wb") as f:
            f.write(upload.file.read())
        drawing_paths.append((drawing.id, saved_path))

    db.commit()
    version_id = version.id

    # Run processing in background so the HTTP response returns immediately
    thread = threading.Thread(
        target=_process_version,
        args=(version_id, drawing_paths),
        daemon=True,
    )
    thread.start()

    return JSONResponse({
        "version_id": version_id,
        "redirect_url": f"/parts/{part_id}/versions/{version_id}/review",
    }, status_code=201)


def _process_version(version_id: int, drawing_paths: list[tuple[int, str]]) -> None:
    """Background task: tile-based dimension extraction pipeline.

    Phase 1: Detect excluded regions (title block, tolerance notes, etc.)
    Phase 2a: pdfplumber text extraction + filter excluded
    Phase 2b: Tile-based LLM extraction (full-res, parallel)
    Phase 3: Reconcile + global sequence numbering
    """
    PDF_SCALE = RASTER_DPI / 72.0  # PDF points → image pixels
    db: Session = SessionLocal()
    _ANTHROPIC_OK = False
    try:
        import anthropic
        _ANTHROPIC_OK = os.getenv("ANTHROPIC_API_KEY") is not None
    except ImportError:
        pass

    try:
        for drawing_id, pdf_path in drawing_paths:
            try:
                # Phase 1: Detect excluded regions (title block, tolerance notes, etc.)
                excluded = []
                if _ANTHROPIC_OK:
                    excluded = detect_excluded_regions(pdf_path)

                # Phase 2a: pdfplumber text extraction + filter excluded
                program_dims = extract_from_pdf(pdf_path)
                program_dims = filter_excluded(program_dims, excluded, is_pixels=False)

                # Phase 2b: Tile-based LLM extraction (full-res, parallel)
                llm_dims: list = []
                if _ANTHROPIC_OK:
                    llm_dims = extract_dimensions_tiled(pdf_path, excluded)

                # Phase 3: Reconcile
                final_dims = reconcile(program_dims, llm_dims, views=None)

                # Sequence numbering (global, no view grouping)
                for seq, dim in enumerate(final_dims, start=1):
                    record = Dimension(
                        drawing_id=drawing_id,
                        sequence=seq,
                        value=dim.value,
                        nominal=dim.nominal,
                        tolerance=dim.tolerance,
                        dim_type=DimensionType(dim.dim_type),
                        view_name=None,
                        source=DimensionSource(dim.source),
                        anchor_x=dim.anchor_x * PDF_SCALE if dim.anchor_x is not None else None,
                        anchor_y=dim.anchor_y * PDF_SCALE if dim.anchor_y is not None else None,
                    )
                    db.add(record)
                db.commit()

                # Generate JPG images for web review
                output_dir = os.path.join(STATIC_DIR, str(drawing_id))
                try:
                    generate_drawing_images(drawing_id, pdf_path, output_dir)
                except Exception as img_err:
                    version = db.query(Version).filter(Version.id == version_id).first()
                    if version:
                        version.notes = (version.notes or "") + f"\n[图片生成失败] drawing {drawing_id}: {img_err}"
                        db.commit()
            except Exception:
                db.rollback()
                raise

        version = db.query(Version).filter(Version.id == version_id).first()
        if version:
            version.status = ProcessingStatus.ready
            db.commit()
    except Exception as exc:
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


@router.post("/{part_id}/versions/{version_id}/reprocess")
def reprocess_images(part_id: int, version_id: int, db: Session = Depends(get_db)):
    version = db.query(Version).filter(Version.id == version_id, Version.part_id == part_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")

    upload_dir = os.path.join(UPLOAD_DIR, str(version_id))
    regenerated = 0
    errors = []

    for drawing in version.drawings:
        # Find the saved PDF for this drawing
        pdf_candidates = [f for f in os.listdir(upload_dir) if f.startswith(f"{drawing.id}_")]
        if not pdf_candidates:
            errors.append(f"drawing {drawing.id}: PDF 文件未找到")
            continue
        pdf_path = os.path.join(upload_dir, pdf_candidates[0])
        output_dir = os.path.join(STATIC_DIR, str(drawing.id))
        try:
            generate_drawing_images(drawing.id, pdf_path, output_dir)
            regenerated += 1
        except Exception as e:
            errors.append(f"drawing {drawing.id}: {e}")

    version.status = ProcessingStatus.ready
    version.notes = (version.notes or "") + f"\n[重新渲染] {regenerated} 张成功"
    if errors:
        version.notes += f"\n错误: {'; '.join(errors)}"
    db.commit()

    return JSONResponse({"ok": True, "regenerated": regenerated, "errors": errors})


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

    return RedirectResponse(url=f"/parts/{part_id}/versions/{version_id}/review", status_code=303)
