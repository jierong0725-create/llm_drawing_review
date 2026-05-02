"""
Vector-PDF dimension extraction prototype.

Pipeline:
  1. pdfplumber → all chars with precise coords
  2. Conservative intra-line tokenization (tight x-gap)
  3. Render full page image, send tokens + image to Sonnet
  4. Sonnet returns: list of dimensions, each = {token_ids, type, value}
  5. Visualize: draw bbox per dimension on page image

Outputs:
  /tmp/pdf_probe/page.png        — original render
  /tmp/pdf_probe/tokens.json     — pre-grouped tokens
  /tmp/pdf_probe/dims.json       — Sonnet output
  /tmp/pdf_probe/viz.png         — annotated visualization
"""

import os
import io
import base64
import json
import math
import re
from itertools import groupby
from pathlib import Path
from collections import defaultdict

import pdfplumber
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
import anthropic

load_dotenv("/Users/rongjie/llm_projects/llm_drawing_review/.env")

PDF = "/Users/rongjie/Desktop/document_pdf.pdf"
OUT = Path("/tmp/pdf_probe")
OUT.mkdir(exist_ok=True)

DPI = 200          # render dpi for visualization
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")


# ── Step 1+2: extract & pre-tokenize ─────────────────────────────────────────

_ANGLE_BIN_DEG = 5  # bucket width for grouping chars by orientation


def _char_angle_deg(c):
    """Return char rotation in degrees, bucketed to _ANGLE_BIN_DEG.

    Uses the matrix's (a, b): local x-axis direction of the glyph.
    No snapping to 90° — supports arbitrary slanted text along leader lines.
    """
    m = c.get("matrix")
    if not m:
        return 0
    a, b = m[0], m[1]
    ang = math.degrees(math.atan2(b, a))
    return int(round(ang / _ANGLE_BIN_DEG) * _ANGLE_BIN_DEG)


def _along_range(c, angle):
    """Project char extents onto the baseline (along) and perpendicular (across).

    Uses the char center for projection; along_lo/hi are derived from char width
    along the baseline so the gap test stays meaningful even for slanted text.
    """
    x0, x1 = c["x0"], c["x1"]
    y0, y1 = c["top"], c["bottom"]
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    width = max(x1 - x0, y1 - y0)  # rough char advance regardless of orientation

    rad = math.radians(angle)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    # PDF top-coord: 'top' grows downward, but matrix uses standard math y-up.
    # In math frame, y_math = -top. So projecting char center:
    along = cos_a * cx + sin_a * (-cy)
    across = -sin_a * cx + cos_a * (-cy)
    return along - width / 2, along + width / 2, across


def extract_tokens():
    with pdfplumber.open(PDF) as pdf:
        page = pdf.pages[0]
        W, H = page.width, page.height
        chars = page.chars
        img = page.to_image(resolution=DPI).original

    inner = [c for c in chars if 30 < c["x0"] < W - 30 and 30 < c["top"] < H - 30]

    # group by snapped angle
    by_angle: dict[int, list] = defaultdict(list)
    for c in inner:
        by_angle[_char_angle_deg(c)].append(c)

    tokens: list[list] = []
    for angle, group in by_angle.items():
        decorated = []  # (across, lo, hi, char)
        for c in group:
            lo, hi, across = _along_range(c, angle)
            decorated.append((across, lo, hi, c))
        decorated.sort(key=lambda d: (round(d[0]), d[1]))
        for _, line in groupby(decorated, key=lambda d: round(d[0])):
            line_list = sorted(line, key=lambda d: d[1])
            cur = [line_list[0]]
            for d in line_list[1:]:
                prev = cur[-1]
                gap = d[1] - prev[2]
                if gap < prev[3]["size"] * 0.35:
                    cur.append(d)
                else:
                    tokens.append([x[3] for x in cur] + [("__angle__", angle)])
                    cur = [d]
            tokens.append([x[3] for x in cur] + [("__angle__", angle)])

    out = []
    for i, t in enumerate(tokens):
        angle = t[-1][1]
        chars_only = t[:-1]
        text = "".join(c["text"] for c in chars_only)
        if not text.strip():
            continue
        # axis-aligned bbox in PDF coords (always page-space)
        out.append({
            "id": i,
            "text": text,
            "angle": angle,
            "x0": round(min(c["x0"] for c in chars_only), 2),
            "y0": round(min(c["top"] for c in chars_only), 2),
            "x1": round(max(c["x1"] for c in chars_only), 2),
            "y1": round(max(c["bottom"] for c in chars_only), 2),
            "size": round(sum(c["size"] for c in chars_only) / len(chars_only), 2),
        })
    return out, img, (W, H)


# ── Step 2.5: detect excluded regions (title block, notes, etc.) ────────────

EXCLUDE_PROMPT = """You are an expert at reading engineering drawings.

Identify TWO kinds of regions on the page and return them BOTH:

(1) views — every distinct view/sub-view that shows part geometry. Includes
    the main view(s), section views, and ENLARGED CALLOUT VIEWS like
    "A (5:1)", "B (5:1)", "C (10:1)". Each view's bbox should tightly enclose
    the geometry + all of that view's own dimensions/leaders.

(2) excluded — administrative/reference regions that contain NO part-specific
    dimensions:
    - title_block: bottom-right table (part number, material, date, BOSCH logo)
    - general_tolerance_notes: column listing DIN/ISO references, default
      Ra (Ra 2, Ra 1.25), default edge tolerances (0.1/-0.25, -0.02/-0.25)
    - technical_notes: NOTES:, MATERIAL SPECIFICATION, CLEANLINESS blocks
    - revision_block: change-history table (Ind/Change/Date)
    - parts_list: BOM table

It is OK if an `excluded` bbox visually overlaps a `view` bbox — we will
subtract views from excluded geometrically. So: draw excluded regions
generously, but do NOT forget to also list every view (especially the
small enlarged callout views A/B/C) so they can be protected.

Return ONLY valid JSON, no markdown:
{{
  "views": [
    {{"name": "main_left",  "bbox": [x1,y1,x2,y2]}},
    {{"name": "A (5:1)",    "bbox": [x1,y1,x2,y2]}},
    {{"name": "B (5:1)",    "bbox": [x1,y1,x2,y2]}},
    {{"name": "C (10:1)",   "bbox": [x1,y1,x2,y2]}}
  ],
  "excluded": [
    {{"type": "title_block",             "bbox": [x1,y1,x2,y2]}},
    {{"type": "general_tolerance_notes", "bbox": [x1,y1,x2,y2]}}
  ]
}}
Coords are image pixels. Image is {w}x{h}."""


# ── Anchor-word + neighbor-flood admin detection (no LLM) ──────────────────

_ADMIN_ANCHORS_RAW = [
    # standards / refs
    "DIN", "ISO", "Allg", "Loengen", "Längen", "Längenmasse",
    # bosch / company
    "BOSCH", "Bosch", "Robert", "GmbH",
    # title-block field labels
    "File:", "Doc.", "Sheet", "Format", "Treatment", "Behandlung",
    "Mat.", "Mat/", "Stoff", "Wght", "Gew", "Crit", "Scale",
    "Repl", "Lang", "MNR", "Drawn", "Checked", "Ind.", "Change",
    "Aend", "Ind/", "Releas", "Resp", "BWN", "Add", "info",
    "Missed", "Angabe", "Aus",
    # notes / specs
    "MATERIAL", "CLEANLINESS", "SPECIFICATION", "NOTES",
    "non-dimensioned", "Nicht bemasste", "burr", "Schnitt",
    "edge tolerance", "Kantentoleranz", "surface texture",
    "Oberfl", "linear dimension", "linear size", "missing TED",
    "Fehlende TED", "interpr",
    # NOTE: "Stamping direction", "Laser welding area",
    # "Surface tension measure area", "Exclude area 0.5 MM from edge",
    # "Screw contact area" are drawing-area callouts (not admin) — do NOT
    # add them as anchors or flood-fill leaks into GD&T frames + Ra 1.25.
    # part type strings
    "EWZ", "ZELLEN", "CONNECTOR", "INTER-CELL", "0442",
    # tolerance class symbols (always in tol notes col)
    "tol. class", "tol.class",
]
_ADMIN_PATTERNS = [
    re.compile(r"(?<!\w)" + re.escape(a) + r"(?!\w)", re.I)
    for a in _ADMIN_ANCHORS_RAW
]


def _is_admin_anchor(text: str) -> bool:
    return any(p.search(text) for p in _ADMIN_PATTERNS)


def _token_box_dist(a, b) -> float:
    """Euclidean distance between two token bboxes (0 if overlapping)."""
    gx = max(0.0, max(a["x0"], b["x0"]) - min(a["x1"], b["x1"]))
    gy = max(0.0, max(a["y0"], b["y0"]) - min(a["y1"], b["y1"]))
    return (gx * gx + gy * gy) ** 0.5


def detect_admin_token_ids(tokens, max_dist: float = 22.0) -> set:
    """Find admin-region tokens by anchor-word seeding + neighbor flood-fill.

    1. Mark tokens whose text contains any admin anchor word as seeds.
    2. Flood-fill: any token within `max_dist` PDF units of an admin token
       becomes admin too.

    Returns set of token IDs.
    """
    n = len(tokens)
    if n == 0:
        return set()

    # adjacency: tokens within max_dist
    adj: list[list[int]] = [[] for _ in range(n)]
    for i in range(n):
        ai = tokens[i]
        for j in range(i + 1, n):
            if _token_box_dist(ai, tokens[j]) < max_dist:
                adj[i].append(j)
                adj[j].append(i)

    seeds = [i for i, t in enumerate(tokens) if _is_admin_anchor(t["text"])]
    visited: set[int] = set(seeds)
    queue = list(seeds)
    while queue:
        i = queue.pop()
        for j in adj[i]:
            if j not in visited:
                visited.add(j)
                queue.append(j)
    return {tokens[i]["id"] for i in visited}


def detect_regions(img: Image.Image, page_size):
    """Detect both views and excluded regions in a single LLM call.

    Returns: {"views": [{name, bbox_pdf}], "excluded": [{type, bbox_pdf}]}
    bbox_pdf coords are in PDF user units.
    """
    W, H = page_size
    iw, ih = img.size
    longest = max(iw, ih)
    max_dim = 1600
    if longest > max_dim:
        r = max_dim / longest
        small = img.resize((int(iw * r), int(ih * r)), Image.LANCZOS)
    else:
        r = 1.0
        small = img
    sw, sh = small.size
    buf = io.BytesIO()
    small.convert("RGB").save(buf, format="JPEG", quality=85)
    b64 = base64.standard_b64encode(buf.getvalue()).decode()

    client = anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        base_url=os.getenv("ANTHROPIC_BASE_URL", "").rstrip("/").removesuffix("/v1") or None,
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": EXCLUDE_PROMPT.format(w=sw, h=sh)},
            ],
        }],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip("` \n")
    data = json.loads(raw)

    # px (downscaled) → original px → PDF units
    upscale = 1.0 / r
    px_to_pdf_x = W / iw
    px_to_pdf_y = H / ih

    def to_pdf(bb):
        x1, y1, x2, y2 = bb
        x1 *= upscale; y1 *= upscale; x2 *= upscale; y2 *= upscale
        return (x1 * px_to_pdf_x, y1 * px_to_pdf_y,
                x2 * px_to_pdf_x, y2 * px_to_pdf_y)

    views = []
    for v in data.get("views", []):
        bb = v.get("bbox", [])
        if len(bb) == 4:
            views.append({"name": v.get("name", ""), "bbox_pdf": to_pdf(bb)})

    excluded = []
    for e in data.get("excluded", []):
        bb = e.get("bbox", [])
        if len(bb) == 4:
            excluded.append({"type": e.get("type", ""), "bbox_pdf": to_pdf(bb)})

    return {"views": views, "excluded": excluded}


def is_excluded_point(cx: float, cy: float, excluded, views) -> bool:
    """A point is "admin" if it's inside ANY excluded bbox AND NOT inside ANY view bbox.

    This is the geometric subtraction: excluded - views.
    """
    in_excl = any(
        e["bbox_pdf"][0] <= cx <= e["bbox_pdf"][2]
        and e["bbox_pdf"][1] <= cy <= e["bbox_pdf"][3]
        for e in excluded
    )
    if not in_excl:
        return False
    in_view = any(
        v["bbox_pdf"][0] <= cx <= v["bbox_pdf"][2]
        and v["bbox_pdf"][1] <= cy <= v["bbox_pdf"][3]
        for v in views
    )
    return not in_view


# ── Step 3: ask Sonnet to group tokens into dimensions ──────────────────────

PROMPT = """You are an expert at reading mechanical engineering drawings.

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
- Do NOT include: title block fields, view labels like "A(5:1)", general notes
  ("Exclude area...", "Stamping direction"), revision marks, frame numbers.
- Datum letter labels in their own boxes (a single "A", "B", "C" with a square
  around them as a datum reference) ARE dimensions (type=datum).
- If a token is part of NO dimension (it's a note/title/etc), omit it.
- Tokens listed for one dimension MUST exist in the input list.

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


def render_image_b64(img: Image.Image, max_dim=2400) -> str:
    w, h = img.size
    longest = max(w, h)
    if longest > max_dim:
        r = max_dim / longest
        img = img.resize((int(w * r), int(h * r)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return base64.standard_b64encode(buf.getvalue()).decode()


def call_llm(tokens, img):
    client = anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        base_url=os.getenv("ANTHROPIC_BASE_URL", "").rstrip("/").removesuffix("/v1") or None,
    )
    b64 = render_image_b64(img)
    text = PROMPT + json.dumps(tokens, ensure_ascii=False)

    resp = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg", "data": b64,
                }},
                {"type": "text", "text": text},
            ],
        }],
    )
    raw = resp.content[0].text.strip()
    # strip code fences if present
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip("` \n")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        (OUT / "llm_raw.txt").write_text(raw)
        print(f"  ! LLM returned non-JSON, dumped to {OUT}/llm_raw.txt (len={len(raw)})")
        raise


# ── Step 5: visualize ───────────────────────────────────────────────────────

def visualize(tokens_by_id, dims, img, page_size):
    W, H = page_size
    iw, ih = img.size
    sx, sy = iw / W, ih / H  # PDF unit → pixel scaling

    canvas = img.convert("RGB").copy()
    draw = ImageDraw.Draw(canvas, "RGBA")

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 14)
        font_sm = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 11)
    except OSError:
        font = font_sm = ImageFont.load_default()

    palette = [
        (255, 80, 80), (80, 160, 255), (60, 200, 100), (220, 140, 40),
        (180, 80, 220), (40, 180, 200), (220, 80, 160), (120, 120, 220),
    ]

    for i, dim in enumerate(dims):
        ids = dim.get("token_ids", [])
        toks = [tokens_by_id[t] for t in ids if t in tokens_by_id]
        if not toks:
            continue
        x0 = min(t["x0"] for t in toks) * sx - 3
        y0 = min(t["y0"] for t in toks) * sy - 3
        x1 = max(t["x1"] for t in toks) * sx + 3
        y1 = max(t["y1"] for t in toks) * sy + 3
        color = palette[i % len(palette)]
        draw.rectangle([x0, y0, x1, y1], outline=color + (255,), width=2)
        label = f"{dim.get('value','?')}"
        # label background
        tb = draw.textbbox((0, 0), label, font=font_sm)
        lw, lh = tb[2] - tb[0], tb[3] - tb[1]
        lx, ly = x0, max(0, y0 - lh - 4)
        draw.rectangle([lx, ly, lx + lw + 6, ly + lh + 4], fill=color + (220,))
        draw.text((lx + 3, ly + 2), label, fill=(255, 255, 255), font=font_sm)

    # legend / summary
    summary = f"Dimensions: {len(dims)}   Tokens: {len(tokens_by_id)}   Model: {MODEL}"
    draw.rectangle([10, 10, 10 + 8 * len(summary) + 10, 36], fill=(0, 0, 0, 200))
    draw.text((16, 14), summary, fill=(255, 255, 255), font=font)

    return canvas


def main():
    print("Step 1+2: extract & tokenize…")
    tokens, img, page_size = extract_tokens()
    print(f"  tokens: {len(tokens)}  page: {page_size}  img: {img.size}")
    img.save(OUT / "page.png")
    (OUT / "tokens.json").write_text(json.dumps(tokens, ensure_ascii=False, indent=2))

    print("Step 2.5: anchor-word + flood-fill admin detection…")
    admin_ids = detect_admin_token_ids(tokens, max_dist=22.0)
    print(f"  admin tokens: {len(admin_ids)} / {len(tokens)}")
    admin_tokens = [t for t in tokens if t["id"] in admin_ids]
    (OUT / "admin_tokens.json").write_text(
        json.dumps(admin_tokens, ensure_ascii=False, indent=2)
    )

    print(f"Step 3: calling {MODEL} on full image with full token list…")
    result = call_llm(tokens, img)
    dims_all = result.get("dimensions", [])
    print(f"  raw dimensions: {len(dims_all)}")

    # Step 4: drop a dim if ALL its tokens are admin tokens.
    dims = []
    dropped = []
    for d in dims_all:
        ids = d.get("token_ids", [])
        if ids and all(tid in admin_ids for tid in ids):
            dropped.append(d)
        else:
            dims.append(d)
    print(f"  dropped (all-admin tokens): {len(dropped)}  → kept: {len(dims)}")
    for d in dropped:
        print(f"    drop: {d.get('value','?')!r}")
    (OUT / "dims.json").write_text(json.dumps({"dimensions": dims, "dropped": dropped},
                                              ensure_ascii=False, indent=2))
    tokens_by_id = {t["id"]: t for t in tokens}

    used_ids = {tid for d in dims for tid in d.get("token_ids", [])}
    print(f"  tokens used: {len(used_ids)}/{len(tokens)}")
    types = {}
    for d in dims:
        types[d.get("type", "?")] = types.get(d.get("type", "?"), 0) + 1
    print(f"  types: {types}")

    print("Step 5: visualize…")
    viz = visualize(tokens_by_id, dims, img, page_size)
    viz.save(OUT / "viz.png")
    print(f"  saved {OUT / 'viz.png'}")


if __name__ == "__main__":
    main()
