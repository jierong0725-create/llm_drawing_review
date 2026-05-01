"""
Step 2: Claude Vision 9-grid check.

Process:
1. Rasterize each PDF page to a 300 DPI image using pdfplumber's page.to_image().
2. Split the full-page image into a 3×3 grid (9 cells).
3. Send each cell to Claude Vision asking it to list all dimension annotations visible.
4. Merge and deduplicate results across all cells and all pages.

Returns a list of ExtractedDimension with source="llm".
"""

import base64
import io
import os
from dataclasses import dataclass
from typing import Optional

import pdfplumber
from PIL import Image

try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

from .extractor import ExtractedDimension, _classify, _parse_nominal_tol, _infer_type

_RESOLUTION = 300   # DPI for rasterisation
_GRID = 3           # 3×3 grid

_SYSTEM_PROMPT = (
    "You are an expert at reading mechanical engineering drawings. "
    "Your task is to identify every dimension annotation in the provided image cell. "
    "Return ONLY a JSON array of strings, each string being the exact text of one dimension "
    "as it appears in the drawing (e.g. \"⌀12.5±0.1\", \"R5\", \"45°\", \"Ra 3.2\", \"69.5 ±0.4\"). "
    "Include: linear dimensions, diameters (⌀/Φ), radii (R), angles, GD&T callouts, "
    "surface roughness (Ra/Rz), and reference dimensions in parentheses. "
    "If no dimensions are visible, return an empty array []. "
    "Return ONLY the JSON array, no other text."
)


def vision_check(pdf_path: str) -> list[ExtractedDimension]:
    """Run Claude Vision on all pages of the PDF and return found dimensions."""
    if not _ANTHROPIC_AVAILABLE:
        return []

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    client = anthropic.Anthropic(api_key=api_key)
    results: list[ExtractedDimension] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            page_img = page.to_image(resolution=_RESOLUTION)
            pil_img: Image.Image = page_img.original
            page_results = _process_page_image(pil_img, page_num, client)
            results.extend(page_results)

    return results


def _process_page_image(img: Image.Image, page_num: int,
                         client) -> list[ExtractedDimension]:
    w, h = img.size
    cell_w = w // _GRID
    cell_h = h // _GRID

    all_texts: list[tuple[str, float, float]] = []  # (text, approx_x, approx_y)

    for row in range(_GRID):
        for col in range(_GRID):
            x0 = col * cell_w
            y0 = row * cell_h
            x1 = x0 + cell_w if col < _GRID - 1 else w
            y1 = y0 + cell_h if row < _GRID - 1 else h
            cell = img.crop((x0, y0, x1, y1))

            texts = _call_vision(cell, client)
            # Approximate anchor = centre of the cell in full-image pixel space
            cx = (x0 + x1) / 2.0
            cy = (y0 + y1) / 2.0
            for t in texts:
                all_texts.append((t, cx, cy))

    # Convert pixel coords at 300 DPI to approximate PDF points (1 pt = 300/72 px)
    scale = 72.0 / _RESOLUTION
    dims: list[ExtractedDimension] = []
    seen: set[str] = set()
    for text, px, py in all_texts:
        text = text.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        nominal, tol = _parse_nominal_tol(text)
        dim_type = _infer_type(text)
        dims.append(ExtractedDimension(
            value=text,
            nominal=nominal,
            tolerance=tol,
            dim_type=dim_type,
            view_name=None,
            source="llm",
            anchor_x=px * scale,
            anchor_y=py * scale,
            page=page_num,
        ))
    return dims


def _call_vision(cell_img: Image.Image, client) -> list[str]:
    """Send one grid cell image to Claude Vision, return list of dimension strings."""
    buf = io.BytesIO()
    cell_img.save(buf, format="JPEG", quality=85)
    b64 = base64.standard_b64encode(buf.getvalue()).decode()

    try:
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": "List all dimension annotations in this drawing cell."},
                    ],
                }
            ],
        )
        raw = response.content[0].text.strip()
        return _parse_json_list(raw)
    except Exception:
        return []


def _parse_json_list(raw: str) -> list[str]:
    import json
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data if x]
    except (json.JSONDecodeError, ValueError):
        pass
    # Fallback: extract quoted strings
    import re
    return re.findall(r'"([^"]+)"', raw)
