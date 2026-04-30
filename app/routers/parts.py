from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import List
import os

from ..database import get_db
from ..models import Part, Version, Drawing, ProcessingStatus, ConfirmResult

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

    # 旧版本标记为非当前版本
    db.query(Version).filter(Version.part_id == part_id).update({"is_current": False})

    version = Version(part_id=part_id, version_code=version_code, is_current=True)
    db.add(version)
    db.flush()

    for i, file in enumerate(files, start=1):
        drawing = Drawing(version_id=version.id, sequence=i, filename=file.filename)
        db.add(drawing)

    db.commit()
    db.refresh(version)

    # TODO: 触发后台处理任务
    version.status = ProcessingStatus.processing
    db.commit()

    return templates.TemplateResponse(
        "parts/detail.html", {"request": request, "part": part}
    )


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

    from datetime import datetime
    version.confirm_result = ConfirmResult(result)
    version.status = ProcessingStatus.confirmed
    version.notes = notes
    version.confirmed_at = datetime.utcnow()
    db.commit()

    part = db.query(Part).filter(Part.id == part_id).first()
    return templates.TemplateResponse("parts/detail.html", {"request": request, "part": part})
