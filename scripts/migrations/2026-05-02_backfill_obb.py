"""Backfill OBB bbox for existing rotated dimensions using token data."""
import math
import sqlite3
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pdfplumber
from app.services.extractor import extract_tokens_vector

PDF_SCALE = 300 / 72.0


def _compute_obb(tokens: list[dict], rotation_deg: float) -> tuple[float, float]:
    """Return (obb_w, obb_h) by projecting char centers onto text direction.

    Uses character centers instead of AABB corners to avoid tilt pollution:
    a single-token AABB height includes the y-offset from tilted text, which
    inflates obb_h when rotating corners. Char centers don't have this bias.
    """
    theta_rad = math.radians(rotation_deg)
    cos_t = math.cos(-theta_rad)
    sin_t = math.sin(-theta_rad)
    projs = []
    max_eff = 0.0
    for t in tokens:
        centers = t.get("char_centers", [])
        if centers:
            for cx, cy in centers:
                projs.append(cos_t * cx + sin_t * cy)
        else:
            projs.append(cos_t * (t["x0"] + t["x1"]) / 2 + sin_t * (t["y0"] + t["y1"]) / 2)
        max_eff = max(max_eff, t.get("eff_size", 0.0) or 0.0)
    if not max_eff:
        max_eff = 10.0
    obb_w = (max(projs) - min(projs)) + max_eff
    return obb_w, max_eff


def backfill(db_path: str, uploads_dir: str):
    con = sqlite3.connect(db_path)
    drawing_ids = [r[0] for r in con.execute(
        "SELECT DISTINCT drawing_id FROM dimensions WHERE rotation_deg != 0"
    ).fetchall()]

    updated_total = 0
    for drawing_id in drawing_ids:
        pdf_path = os.path.join(uploads_dir, str(drawing_id), f"{drawing_id}_document_pdf.pdf")
        if not os.path.exists(pdf_path):
            print(f"  drawing {drawing_id}: PDF not found, skipping")
            continue

        try:
            with pdfplumber.open(pdf_path) as pdf:
                tokens = extract_tokens_vector(pdf.pages[0])
        except Exception as e:
            print(f"  drawing {drawing_id}: token extraction failed ({e}), skipping")
            continue

        dims = con.execute(
            "SELECT id, anchor_x, anchor_y, rotation_deg, bbox_x0, bbox_y0, bbox_x1, bbox_y1 "
            "FROM dimensions WHERE drawing_id = ? AND rotation_deg != 0",
            (drawing_id,),
        ).fetchall()

        updated = 0
        for dim_id, ax, ay, rot, bx0, by0, bx1, by1 in dims:
            if ax is None:
                continue
            ax_pt = ax / PDF_SCALE
            ay_pt = ay / PDF_SCALE

            if bx0 is not None:
                # Use existing bbox region + margin
                bx0_pt, by0_pt = bx0 / PDF_SCALE, by0 / PDF_SCALE
                bx1_pt, by1_pt = bx1 / PDF_SCALE, by1 / PDF_SCALE
                margin = max(bx1_pt - bx0_pt, by1_pt - by0_pt) * 0.25
                candidates = [
                    t for t in tokens
                    if abs(t["theta"] - rot) < 15
                    and bx0_pt - margin <= (t["x0"] + t["x1"]) / 2 <= bx1_pt + margin
                    and by0_pt - margin <= (t["y0"] + t["y1"]) / 2 <= by1_pt + margin
                ]
            else:
                # No bbox: search within fixed radius around anchor
                radius = 80  # PDF points (~2.7 cm at 1:1)
                candidates = [
                    t for t in tokens
                    if abs(t["theta"] - rot) < 15
                    and abs((t["x0"] + t["x1"]) / 2 - ax_pt) < radius
                    and abs((t["y0"] + t["y1"]) / 2 - ay_pt) < radius
                ]

            if not candidates:
                continue

            obb_w, obb_h = _compute_obb(candidates, rot)
            new_bx0 = (ax_pt - obb_w / 2) * PDF_SCALE
            new_bx1 = (ax_pt + obb_w / 2) * PDF_SCALE
            new_by0 = (ay_pt - obb_h / 2) * PDF_SCALE
            new_by1 = (ay_pt + obb_h / 2) * PDF_SCALE

            con.execute(
                "UPDATE dimensions SET bbox_x0=?, bbox_y0=?, bbox_x1=?, bbox_y1=? WHERE id=?",
                (new_bx0, new_by0, new_bx1, new_by1, dim_id),
            )
            updated += 1

        con.commit()
        print(f"  drawing {drawing_id}: updated {updated}/{len(dims)} rotated dimensions")
        updated_total += updated

    con.close()
    print(f"\nTotal OBB-updated: {updated_total}")


if __name__ == "__main__":
    backfill("dev.db", "app/static/uploads")
