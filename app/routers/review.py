from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime
import os

from ..database import get_db
from ..models import (
    Part, Version, Drawing, Dimension, ReviewMessage,
    ProcessingStatus, ConfirmResult, DimensionType, DimensionSource, ReviewStatus,
)

router = APIRouter(prefix="/parts", tags=["review"])
api = APIRouter(prefix="/api")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "../templates"))


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------

@router.get("/{part_id}/versions/{version_id}/review", response_class=HTMLResponse)
def review_page(request: Request, part_id: int, version_id: int, db: Session = Depends(get_db)):
    part = db.query(Part).filter(Part.id == part_id).first()
    if not part:
        raise HTTPException(status_code=404, detail="零件不存在")
    version = db.query(Version).filter(Version.id == version_id, Version.part_id == part_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")
    return templates.TemplateResponse(request, "review_workbench.html", {
        "title": f"{part.name} — 图纸审核",
    })


# ---------------------------------------------------------------------------
# Version APIs
# ---------------------------------------------------------------------------

@api.get("/parts/{part_id}/versions")
def list_versions(part_id: int, db: Session = Depends(get_db)):
    versions = db.query(Version).filter(Version.part_id == part_id).order_by(Version.created_at.desc()).all()
    return [{"id": v.id, "version_code": v.version_code, "is_current": v.is_current,
             "status": v.status.value, "confirm_result": v.confirm_result.value if v.confirm_result else None,
             "created_at": v.created_at.strftime("%Y-%m-%d %H:%M") if v.created_at else None}
            for v in versions]


@api.get("/versions/{version_id}/drawings")
def list_drawings(version_id: int, db: Session = Depends(get_db)):
    drawings = db.query(Drawing).filter(Drawing.version_id == version_id).order_by(Drawing.sequence).all()
    return [{"id": d.id, "sequence": d.sequence, "filename": d.filename} for d in drawings]


# ---------------------------------------------------------------------------
# Dimension CRUD APIs
# ---------------------------------------------------------------------------

@api.get("/versions/{version_id}/drawings/{drawing_id}/dimensions")
def list_dimensions(version_id: int, drawing_id: int, db: Session = Depends(get_db)):
    dims = db.query(Dimension).filter(Dimension.drawing_id == drawing_id).order_by(Dimension.sequence).all()
    return JSONResponse([{
        "id": d.id, "sequence": d.sequence, "value": d.value,
        "nominal": d.nominal, "tolerance": d.tolerance, "dim_type": d.dim_type.value,
        "source": d.source.value, "anchor_x": d.anchor_x, "anchor_y": d.anchor_y,
        "view_name": d.view_name,
        "review_status": d.review_status.value if d.review_status else "pending",
        "message_count": len(d.messages) if d.messages else 0,
    } for d in dims])


@api.post("/dimensions")
async def create_dimension(request: Request):
    data = await request.json()
    db: Session = next(get_db())
    try:
        dim = Dimension(
            drawing_id=data["drawing_id"], sequence=data["sequence"],
            value=data["value"], nominal=data.get("nominal"),
            tolerance=data.get("tolerance"),
            dim_type=DimensionType(data["dim_type"]),
            anchor_x=data.get("anchor_x"), anchor_y=data.get("anchor_y"),
            source=DimensionSource.llm, review_status=ReviewStatus.pending,
        )
        db.add(dim)
        db.commit()
        db.refresh(dim)
        return JSONResponse({"id": dim.id, "sequence": dim.sequence}, status_code=201)
    finally:
        db.close()


@api.patch("/dimensions/{dimension_id}")
async def update_dimension(dimension_id: int, request: Request):
    data = await request.json()
    db: Session = next(get_db())
    try:
        dim = db.query(Dimension).filter(Dimension.id == dimension_id).first()
        if not dim:
            raise HTTPException(status_code=404)
        for key in ("sequence", "value", "nominal", "tolerance", "anchor_x", "anchor_y", "view_name"):
            if key in data:
                setattr(dim, key, data[key])
        if "dim_type" in data:
            dim.dim_type = DimensionType(data["dim_type"])
        if "review_status" in data:
            dim.review_status = ReviewStatus(data["review_status"])
        db.commit()
        return JSONResponse({"ok": True})
    finally:
        db.close()


@api.delete("/dimensions/{dimension_id}")
def delete_dimension(dimension_id: int, db: Session = Depends(get_db)):
    dim = db.query(Dimension).filter(Dimension.id == dimension_id).first()
    if not dim:
        raise HTTPException(status_code=404)
    db.query(ReviewMessage).filter(ReviewMessage.dimension_id == dimension_id).delete()
    db.delete(dim)
    db.commit()
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Discussion message APIs
# ---------------------------------------------------------------------------

@api.get("/dimensions/{dimension_id}/messages")
def list_messages(dimension_id: int, db: Session = Depends(get_db)):
    msgs = db.query(ReviewMessage).filter(
        ReviewMessage.dimension_id == dimension_id
    ).order_by(ReviewMessage.created_at).all()
    return JSONResponse([{
        "id": m.id, "author": m.author, "content": m.content,
        "created_at": m.created_at.strftime("%Y-%m-%d %H:%M"),
    } for m in msgs])


@api.post("/dimensions/{dimension_id}/messages")
async def create_message(dimension_id: int, request: Request):
    data = await request.json()
    db: Session = next(get_db())
    try:
        msg = ReviewMessage(
            dimension_id=dimension_id, author=data["author"],
            content=data["content"],
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)
        return JSONResponse({
            "id": msg.id, "author": msg.author, "content": msg.content,
            "created_at": msg.created_at.strftime("%Y-%m-%d %H:%M"),
        }, status_code=201)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Conclusion API
# ---------------------------------------------------------------------------

@api.patch("/versions/{version_id}/conclusion")
async def submit_conclusion(version_id: int, request: Request):
    data = await request.json()
    db: Session = next(get_db())
    try:
        version = db.query(Version).filter(Version.id == version_id).first()
        if not version:
            raise HTTPException(status_code=404)
        version.confirm_result = ConfirmResult(data["result"])
        version.status = ProcessingStatus.confirmed
        version.notes = data.get("notes", "")
        version.confirmed_at = datetime.utcnow()
        db.commit()
        return JSONResponse({"ok": True})
    finally:
        db.close()
