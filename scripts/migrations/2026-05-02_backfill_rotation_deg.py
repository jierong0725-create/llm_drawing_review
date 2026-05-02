"""Backfill rotation_deg for existing dimensions using nearest token theta."""
import math
import sqlite3
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pdfplumber
from app.services.extractor import extract_tokens_vector

PDF_SCALE = 300 / 72.0  # DB coords are 300-DPI pixels; tokens are PDF points


def _nearest_theta(tokens: list[dict], ax: float, ay: float) -> float:
    """Return theta of the token whose center is closest to (ax, ay) in PDF pts."""
    if not tokens:
        return 0.0
    best, best_d = tokens[0], float("inf")
    for t in tokens:
        cx = (t["x0"] + t["x1"]) / 2
        cy = (t["y0"] + t["y1"]) / 2
        d = math.hypot(cx - ax, cy - ay)
        if d < best_d:
            best, best_d = t, d
    return best["theta"]


def backfill(db_path: str, uploads_dir: str):
    con = sqlite3.connect(db_path)
    drawing_ids = [r[0] for r in con.execute(
        "SELECT DISTINCT drawing_id FROM dimensions WHERE rotation_deg = 0"
    ).fetchall()]

    updated_total = 0
    for drawing_id in drawing_ids:
        pdf_path = os.path.join(uploads_dir, str(drawing_id), f"{drawing_id}_document_pdf.pdf")
        if not os.path.exists(pdf_path):
            print(f"  drawing {drawing_id}: PDF not found at {pdf_path}, skipping")
            continue

        try:
            with pdfplumber.open(pdf_path) as pdf:
                page = pdf.pages[0]
                tokens = extract_tokens_vector(page)
        except Exception as e:
            print(f"  drawing {drawing_id}: token extraction failed ({e}), skipping")
            continue

        dims = con.execute(
            "SELECT id, anchor_x, anchor_y FROM dimensions WHERE drawing_id = ?",
            (drawing_id,),
        ).fetchall()

        updated = 0
        for dim_id, ax_px, ay_px in dims:
            if ax_px is None or ay_px is None:
                continue
            ax_pt = ax_px / PDF_SCALE
            ay_pt = ay_px / PDF_SCALE
            theta = _nearest_theta(tokens, ax_pt, ay_pt)
            if abs(theta) > 2:  # only update genuinely rotated dims
                con.execute(
                    "UPDATE dimensions SET rotation_deg = ? WHERE id = ?",
                    (round(theta, 2), dim_id),
                )
                updated += 1

        con.commit()
        print(f"  drawing {drawing_id}: updated {updated}/{len(dims)} dimensions")
        updated_total += updated

    con.close()
    print(f"\nTotal updated: {updated_total}")


if __name__ == "__main__":
    backfill("dev.db", "app/static/uploads")
