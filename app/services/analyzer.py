"""
Phase 1 + 2b + 4: LLM-powered structural analysis and view-based dimension extraction.

Replaces the old 3×3 grid approach (vision.py) with:
- Full-page structural analysis for view/excluded region detection
- Per-view cropped image extraction for better coverage and accuracy
- Verification loop for missing dimension detection
"""

import base64
import io
import json
import os
from dataclasses import dataclass
from typing import Optional

import pdfplumber
from PIL import Image

from .extractor import ExtractedDimension, _parse_nominal_tol, _infer_type

from math import ceil
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

_RESOLUTION = 300
_JPEG_QUALITY = 85
_TARGET_MAX_TILES = 30
_BASE_TILE_SIZE = 1400
_BASE_OVERLAP = 200

_MODEL = "claude-opus-4-7"


def compute_tile_grid(w: int, h: int) -> tuple[list[tuple[int, int, int, int]], int]:
    """Return (tiles, overlap). tiles are (x0, y0, x1, y1) in full-image pixels.

    Tile size grows until the grid fits within _TARGET_MAX_TILES (handles A0).
    """
    tile_size = _BASE_TILE_SIZE
    overlap = _BASE_OVERLAP
    for t in range(_BASE_TILE_SIZE, 3100, 100):
        stride = t - _BASE_OVERLAP
        if ceil(w / stride) * ceil(h / stride) <= _TARGET_MAX_TILES:
            tile_size = t
            break
    else:
        tile_size = 3000
        overlap = 300

    stride = tile_size - overlap
    tiles: list[tuple[int, int, int, int]] = []
    for row in range(ceil(h / stride)):
        for col in range(ceil(w / stride)):
            x0 = col * stride
            y0 = row * stride
            x1 = min(x0 + tile_size, w)
            y1 = min(y0 + tile_size, h)
            tiles.append((x0, y0, x1, y1))
    return tiles, overlap


def _dedup(dims: list, radius: float) -> list:
    """Remove duplicate dimensions within overlap zones.

    Two dims are duplicates if their text matches and their centers are
    within `radius` pixels of each other in full-image space.
    """
    kept: list = []
    for d in dims:
        if d.anchor_x is None or d.anchor_y is None:
            kept.append(d)
            continue
        is_dup = any(
            d.value == k.value
            and k.anchor_x is not None
            and k.anchor_y is not None
            and abs(d.anchor_x - k.anchor_x) < radius
            and abs(d.anchor_y - k.anchor_y) < radius
            for k in kept
        )
        if not is_dup:
            kept.append(d)
    return kept


@dataclass
class ViewRegion:
    name: str
    bbox: tuple[int, int, int, int]  # (left, top, right, bottom) in 300 DPI pixels
    page: int


@dataclass
class ExcludedRegion:
    region_type: str  # "title_block" | "technical_notes" | "parts_list"
    bbox: tuple[int, int, int, int]


_EXCLUDED_PROMPT = """You are an expert at reading engineering drawings.

Scan the edges and corners of this drawing frame. Find every region that contains
administrative/reference information rather than part-specific dimensions:

- title_block: bottom-right corner, table-like layout with part number, material,
  date, revision, company logo/name. ALWAYS mark this as excluded.
- general_tolerance_notes: a box (typically right side) listing DIN/ISO standard
  references, default Ra surface roughness values, edge tolerances, burr height
  limits. ALWAYS mark this as excluded.
- technical_notes: text blocks with NOTES:, MATERIAL SPECIFICATION, SURFACE
  TREATMENT, CLEANLINESS, etc.
- revision_block: a table listing engineering change history (Ind./Change/Date).
- parts_list: a BOM table listing component items, usually above the title block.

Return ONLY valid JSON (no markdown, no code fences):
{{
  "excluded_regions": [
    {{"region_type": "title_block",             "bbox": [x1, y1, x2, y2]}},
    {{"region_type": "general_tolerance_notes", "bbox": [x1, y1, x2, y2]}}
  ]
}}

Coordinates are image pixels. bbox = [x1, y1, x2, y2] where (x1,y1) is top-left.
The image is {width}x{height} pixels."""

_STRUCTURE_MAX_DIM = 1600


def detect_excluded_regions(pdf_path: str) -> list[ExcludedRegion]:
    """Phase 1 (simplified): detect excluded regions only, no view detection."""
    if not _ANTHROPIC_AVAILABLE:
        return []

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    client = anthropic.Anthropic(api_key=api_key)

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        page_img = page.to_image(resolution=_RESOLUTION)
        pil_img: Image.Image = page_img.original
        full_w, full_h = pil_img.size

        longest = max(full_w, full_h)
        if longest > _STRUCTURE_MAX_DIM:
            ratio = _STRUCTURE_MAX_DIM / longest
            send_img = pil_img.resize(
                (int(full_w * ratio), int(full_h * ratio)), Image.LANCZOS
            )
        else:
            ratio = 1.0
            send_img = pil_img

        send_w, send_h = send_img.size
        b64 = _image_to_base64(send_img)

    prompt = _EXCLUDED_PROMPT.format(width=send_w, height=send_h)

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=512,
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
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        raw = response.content[0].text.strip()
        data = json.loads(raw)
        upscale = 1.0 / ratio if ratio != 1.0 else 1.0
        excluded: list[ExcludedRegion] = []
        for e in data.get("excluded_regions", []):
            bbox = e.get("bbox", [])
            if len(bbox) != 4:
                continue
            l, t, r, b = bbox
            if not (0 <= l < r <= send_w and 0 <= t < b <= send_h):
                continue
            excluded.append(ExcludedRegion(
                region_type=str(e.get("region_type", "")),
                bbox=(
                    int(l * upscale), int(t * upscale),
                    int(r * upscale), int(b * upscale),
                ),
            ))
        return excluded
    except (json.JSONDecodeError, KeyError, ValueError):
        return []


# ── Phase 2b: Per-view LLM extraction ──

_EXTRACT_PROMPT = """You are an expert at reading mechanical engineering drawings.

This image shows ONE cropped view from an engineering drawing. Identify EVERY dimension annotation visible in this view.

For each dimension, return:
{
  "dimensions": [
    {
      "text": "the exact dimension text as it appears (e.g. \\u2ACC12.5\\u00B10.1, R5, 45\\u00B0, M10\\u00D71.5, 2\\u00D7\\u2ACC8, Ra 3.2, 69.5 \\u00B10.4, [\\u2ACC20]\\u2295|\\u2ACC0.05|A|B|C)",
      "x": <estimated center X coordinate within this cropped image in pixels>,
      "y": <estimated center Y coordinate within this cropped image in pixels>
    }
  ]
}

Include ALL types:
- Linear dimensions (numbers with tolerance \\u00B1)
- Diameters (\\u2ACC, \\u03A6, \\u03C6)
- Radii (R)
- Angles (\\u00B0)
- GD&T feature control frames (\\u2295, \\u2298, etc.)
- Surface roughness (Ra, Rz)
- Thread callouts (M, Tr, G)
- Count/dimension patterns (e.g. "2\\u00D7\\u2ACC8", "6\\u00D7M6")
- Reference dimensions in parentheses
- Chamfer callouts (C, C\\u00D745\\u00B0)

CRITICAL: Return EVERY visible dimension. Missing even one is a failure.
Do NOT include: view title text, notes, or general drawing annotations.
Return ONLY valid JSON, no markdown, no code fences.
The image is {crop_width}x{crop_height} pixels."""


def extract_view_dimensions(image: Image.Image, view: ViewRegion, page_num: int, client) -> list[ExtractedDimension]:
    """Phase 2b: Extract dimensions from a single cropped view using Claude Vision."""
    crop = image.crop(view.bbox)
    crop_w, crop_h = crop.size
    b64 = _image_to_base64(crop)
    prompt = _EXTRACT_PROMPT.format(crop_width=crop_w, crop_height=crop_h)

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=2048,
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
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        raw = response.content[0].text.strip()
        data = _parse_json_dict(raw)
    except (json.JSONDecodeError, KeyError):
        return []

    dims: list[ExtractedDimension] = []
    seen_texts: set[str] = set()
    for item in data.get("dimensions", []):
        text = str(item.get("text", "")).strip()
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)

        x = item.get("x")
        y = item.get("y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            continue
        if x < 0 or y < 0 or x > crop_w or y > crop_h:
            continue

        full_x = x + view.bbox[0]
        full_y = y + view.bbox[1]
        nominal, tol = _parse_nominal_tol(text)
        dim_type = _infer_type(text)
        dims.append(ExtractedDimension(
            value=text, nominal=nominal, tolerance=tol,
            dim_type=dim_type, view_name=view.name,
            source="llm", anchor_x=full_x, anchor_y=full_y, page=page_num,
        ))

    return dims


# ── Phase 4: Verification loop ──

_VERIFY_PROMPT = """You are an expert at reading mechanical engineering drawings.

This image shows ONE cropped view from an engineering drawing. Below is a list of dimensions that have already been identified in this view:

{text_list}

Review the cropped view image carefully. Are there ANY additional dimensions visible that are NOT in the list above?

- Look carefully at all areas of the image
- Check corners, edges, and areas between already-identified dimensions
- Include linear dimensions, diameters (\\u2ACC/\\u03A6), radii (R), angles (\\u00B0), GD&T, surface roughness, thread callouts
- Do NOT include view titles, general notes text, or title block text

If you find missing dimensions, return them as a JSON array of strings.
If all dimensions are accounted for, return an empty array [].

Return ONLY a JSON array, no markdown, no code fences."""


def verify_coverage(image: Image.Image, view: ViewRegion, dims_in_view: list[ExtractedDimension],
                    page_num: int, client) -> list[str]:
    """Phase 4: Check a view for missed dimensions."""
    if not dims_in_view:
        return []

    crop = image.crop(view.bbox)
    b64 = _image_to_base64(crop)
    texts = [d.value for d in dims_in_view]
    text_list = "\n".join(f"- {t}" for t in texts)
    prompt = _VERIFY_PROMPT.format(text_list=text_list)

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
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
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        raw = response.content[0].text.strip()
        data = _parse_json_list(raw)
        return [str(x) for x in data if x]
    except (json.JSONDecodeError, KeyError):
        return []


# ── Helpers ──

def _image_to_base64(img: Image.Image, quality: int = _JPEG_QUALITY) -> str:
    """PIL Image → base64 JPEG string."""
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.standard_b64encode(buf.getvalue()).decode()


def _parse_json_list(raw: str) -> list:
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    # Fallback: extract quoted strings
    import re
    return re.findall(r'"([^"]+)"', raw)


def _parse_json_dict(raw: str) -> dict:
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return {}
