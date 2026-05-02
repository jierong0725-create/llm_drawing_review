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
import statistics
from dataclasses import dataclass
from typing import Optional

import pdfplumber
from PIL import Image

from .extractor import ExtractedDimension, _parse_nominal_tol, _infer_type, extract_tokens_vector

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

_MODEL = "claude-sonnet-4.6"


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
{{
  "dimensions": [
    {{
      "text": "the exact dimension text as it appears (e.g. \\u2ACC12.5\\u00B10.1, R5, 45\\u00B0, M10\\u00D71.5, 2\\u00D7\\u2ACC8, Ra 3.2, 69.5 \\u00B10.4, [\\u2ACC20]\\u2295|\\u2ACC0.05|A|B|C)",
      "x": <estimated center X coordinate within this cropped image in pixels>,
      "y": <estimated center Y coordinate within this cropped image in pixels>
    }}
  ]
}}

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


def extract_dimensions_tiled(
    pdf_path: str,
    excluded: list[ExcludedRegion],
) -> list[ExtractedDimension]:
    """Tile-based full-drawing LLM dimension extraction.

    Splits the full-resolution drawing into overlapping tiles, extracts dimensions
    from each tile in parallel, deduplicates overlap zones, then filters excluded
    regions.
    """
    if not _ANTHROPIC_AVAILABLE:
        return []

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        page_img = page.to_image(resolution=_RESOLUTION)
        pil_img: Image.Image = page_img.original
        w, h = pil_img.size

    tiles, overlap = compute_tile_grid(w, h)
    radius = overlap * 0.8
    client = anthropic.Anthropic(api_key=api_key)

    def _extract_tile(tile_bbox: tuple[int, int, int, int]) -> list[ExtractedDimension]:
        dummy_view = ViewRegion(name="tile", bbox=tile_bbox, page=1)
        return extract_view_dimensions(pil_img, dummy_view, 1, client)

    all_dims: list[ExtractedDimension] = []
    with ThreadPoolExecutor(max_workers=min(len(tiles), 8)) as executor:
        futures = {executor.submit(_extract_tile, t): t for t in tiles}
        for future in as_completed(futures):
            try:
                all_dims.extend(future.result())
            except Exception:
                pass

    all_dims = _dedup(all_dims, radius)

    if excluded:
        all_dims = [
            d for d in all_dims
            if not any(
                e.bbox[0] <= (d.anchor_x or -1) <= e.bbox[2]
                and e.bbox[1] <= (d.anchor_y or -1) <= e.bbox[3]
                for e in excluded
            )
        ]

    return all_dims


# ── Phase 2b (vector): single-call token-based extraction ────────────────────

_VECTOR_PROMPT = """You are an expert at reading mechanical engineering drawings.

You are given:
1. A rendered image of an engineering drawing (1 page).
2. A complete list of all text tokens extracted from the drawing's vector PDF
   layer. Each token has: id, text, bbox in PDF user units (x0,y0,x1,y1).

Your job: identify EVERY dimension annotation on the drawing, and for each one,
return the list of token IDs that compose it.

A "dimension annotation" is one logical measurement: e.g.
- A linear dim with optional tolerance: tokens like "12.5", "+0.1", "-0.1"
  stacked vertically are ONE dimension.
- A diameter: "⌀12" or "12" near a ⌀ symbol → ONE dimension.
- A radius: "R5" or "R" + "5" → ONE dimension.
- A count×dim pattern: "2X" + "⌀8" near each other → ONE dimension.
- A GD&T feature control frame: the symbol cell + tolerance + datum letters
  inside one rectangle → ONE dimension.
- A surface roughness callout: "Ra 1.25" → ONE dimension.

Rules:
- Group tokens that visually belong to the SAME dimension callout (same leader
  line, same tolerance stack, same feature control frame).
- Do NOT include: title block fields, view labels like "A(5:1)" / "B(5:1)" /
  "C(10:1)", general notes ("Exclude area...", "Stamping direction"),
  revision marks, frame numbers.
- Datum letter labels in their own boxes (a single "A", "B", "C" enclosed by a
  SQUARE BOX as a datum reference) ARE dimensions (type=datum). Use the image
  to disambiguate from view labels — datum boxes are small squares with no
  scale text like "(5:1)" next to them.
- If a token is part of NO dimension (it's a note/title/etc), omit it.
- Tokens listed for one dimension MUST exist in the input list.

CRITICAL grouping patterns — these are commonly missed, you MUST handle them:

1. Count prefixes "nX" / "nx" / "n×" (e.g. "4X", "2X", "6X"):
   - MUST be merged with the dimension they multiply, even when separated by
     a large whitespace gap or sitting on a leader line. Examples:
       "4X" + "(R 0.2)"     → ONE count_dim "4X(R0.2)"
       "2X" + "⌀8"          → ONE count_dim "2X⌀8"
       "2X" + "R2" + "±0.4" → ONE count_dim "2XR2±0.4"
   - Look along the same leader line / arrow, not just adjacent tokens.

2. "nXmax" / "nXmin" callouts (e.g. "4Xmax", "4Xmin"):
   - When followed by a numeric value, the pair is ONE dimension.
     "4Xmax" + "0.3" → ONE count_dim "4Xmax 0.3"
     "4Xmin" + "0.7" → ONE count_dim "4Xmin 0.7"

3. Vertically stacked tolerance / nominal pairs:
   - A nominal value with a tolerance line BELOW or ABOVE it on a different
     baseline is ONE dimension. Examples:
       "1.2"      (top)
       "±0.05"    (below)            → ONE linear "1.2 ±0.05"

       "17.9"     (top)
       "+0.2"     (next line)
       "-0.6"     (next line)        → ONE linear "17.9 +0.2/-0.6"
   - This applies to BOTH horizontal AND rotated/vertical dimension callouts.

4. When in doubt about whether a small isolated token (single number, single
   letter, "nX", "±x.x") is part of an existing dimension, prefer to MERGE
   it into the nearest dimension along the same leader line rather than
   omit it.

5. Angle dimensions with separate tolerance line:
   - An angle nominal (e.g. "155", "47.81") and a small isolated number on
     a nearby line / arc (e.g. "3", "2") are ONE angle dimension where the
     second number is the ± tolerance in degrees, even though the °/± symbols
     are drawn as vector glyphs and missing from the token list.
       "2X" + "155" + "3"      → ONE angle "2X 155°±3°"
       "47.81" + "2"           → ONE angle "47.81°±2°"
   - Trigger: small same-size tokens (typically size < 5) along the same
     arc/leader, with no other dimension nearby. Use type="angle".

6. GD&T feature control frames — symbol disambiguation:
   - The leftmost cell of a GD&T frame holds a symbol that is drawn as
     vector geometry and is NOT in the token list. You MUST look at the
     image to identify which symbol it is. Common ones:
       ⏥  flatness           (parallelogram)
       ⌒  profile of a line  (open arc / half-circle on top)
       ⌓  profile of surface
       ⊕  position           (crosshair circle)
       ⊙  concentricity
       ⌭  cylindricity
       ∥  parallelism
       ⟂  perpendicularity
       ∠  angularity
       ⌯  symmetry
   - Encode the actual symbol in `value`, e.g. "⏥ 0.2", "⌒ 0.3 A B C".
     Do NOT default to ⊕ when the frame clearly shows a different symbol.
   - Each GD&T frame is ONE dimension. Tokens inside that frame must be
     spatially adjacent (same small rectangle in the image). NEVER merge
     a "0.2" from one frame with another "0.2" elsewhere on the drawing —
     each frame is independent. Use type="gdt".

Return ONLY valid JSON, no markdown:
{
  "dimensions": [
    {
      "token_ids": [12, 13, 14],
      "type": "linear|diameter|radius|angle|gdt|roughness|thread|chamfer|datum|count_dim",
      "value": "concatenated/normalized text e.g. '69.5±0.4', '⌀12', 'R5', 'Ra 1.25'"
    }
  ]
}

Tokens (JSON):
"""

_VECTOR_DPI = 200
_VECTOR_MAX_DIM = 2400


def extract_dimensions_vector(pdf_path: str) -> list[ExtractedDimension]:
    """Single-call vector-token dimension extraction (replaces tiled approach).

    For each page:
      1. Extract rotation-aware tokens from PDF vector layer (PDF-point coords).
      2. Render full-page image at 200 DPI.
      3. One LLM call: image + token list → token_id groupings + type + value.
      4. Map token_ids back to anchor coords (mean of token bbox centers, PDF pts).
    """
    if not _ANTHROPIC_AVAILABLE:
        return []
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    client = anthropic.Anthropic(
        api_key=api_key,
        base_url=(os.getenv("ANTHROPIC_BASE_URL", "").rstrip("/").removesuffix("/v1") or None),
    )

    results: list[ExtractedDimension] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            tokens = extract_tokens_vector(page)
            if not tokens:
                continue

            img: Image.Image = page.to_image(resolution=_VECTOR_DPI).original
            w, h = img.size
            longest = max(w, h)
            if longest > _VECTOR_MAX_DIM:
                r = _VECTOR_MAX_DIM / longest
                send_img = img.resize((int(w * r), int(h * r)), Image.LANCZOS)
            else:
                send_img = img

            b64 = _image_to_base64(send_img)
            # Send only id/text/bbox to LLM — char_centers/theta are not needed for grouping
            tokens_for_llm = [
                {"id": t["id"], "text": t["text"],
                 "x0": t["x0"], "y0": t["y0"], "x1": t["x1"], "y1": t["y1"]}
                for t in tokens
            ]
            import json as _json
            prompt_text = _VECTOR_PROMPT + _json.dumps(tokens_for_llm, ensure_ascii=False)

            try:
                response = client.messages.create(
                    model=_MODEL,
                    max_tokens=8192,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {
                                "type": "base64", "media_type": "image/jpeg", "data": b64,
                            }},
                            {"type": "text", "text": prompt_text},
                        ],
                    }],
                )
                data = _parse_json_dict(response.content[0].text.strip())
            except Exception as e:
                raise RuntimeError(f"vector extraction failed on page {page_num}: {e}") from e

            tokens_by_id = {t["id"]: t for t in tokens}
            for dim in data.get("dimensions", []):
                ids = dim.get("token_ids", [])
                toks = [tokens_by_id[i] for i in ids if i in tokens_by_id]
                if not toks:
                    continue
                ax = sum((t["x0"] + t["x1"]) / 2 for t in toks) / len(toks)
                ay = sum((t["y0"] + t["y1"]) / 2 for t in toks) / len(toks)
                value = str(dim.get("value", "")).strip()
                raw_type = str(dim.get("type", "linear"))
                _TYPE_MAP = {
                    "count_dim": "linear", "datum": "reference",
                    "thread": "linear", "chamfer": "linear",
                }
                dim_type = _TYPE_MAP.get(raw_type, raw_type)
                if dim_type not in ("linear", "diameter", "radius", "angle",
                                    "gdt", "roughness", "reference"):
                    dim_type = _infer_type(value)
                nominal, tol = _parse_nominal_tol(value)
                thetas = [t["theta"] for t in toks if "theta" in t]
                rotation = statistics.median(thetas) if thetas else 0.0

                # Compute OBB by projecting char centers onto text direction.
                # Stored as "virtual AABB" (cx ± obbW/2, cy ± obbH/2) so the
                # frontend can use bbox width/height directly without AABB→OBB inversion.
                theta_rad = math.radians(rotation)
                cos_t = math.cos(-theta_rad)
                sin_t = math.sin(-theta_rad)
                # Project char centers onto text direction to avoid AABB tilt pollution.
                # Single-token AABB height includes y-offset from tilted text, which
                # inflates obb_h when rotating corners. Char centers don't have this bias.
                projs = []
                max_eff = 0.0
                for t in toks:
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
                obb_h = max_eff
                bx0 = ax - obb_w / 2
                bx1 = ax + obb_w / 2
                by0 = ay - obb_h / 2
                by1 = ay + obb_h / 2

                results.append(ExtractedDimension(
                    value=value, nominal=nominal, tolerance=tol,
                    dim_type=dim_type, view_name=None,
                    source="llm", anchor_x=ax, anchor_y=ay, page=page_num,
                    bbox_x0=bx0, bbox_y0=by0, bbox_x1=bx1, bbox_y1=by1,
                    rotation_deg=rotation,
                ))

    return results


# ── Helpers ──

def _image_to_base64(img: Image.Image, quality: int = _JPEG_QUALITY) -> str:
    """PIL Image → base64 JPEG string."""
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.standard_b64encode(buf.getvalue()).decode()


def _parse_json_dict(raw: str) -> dict:
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return {}
