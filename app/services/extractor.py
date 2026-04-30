"""
Step 1: pdfplumber-based dimension extraction.

Strategy:
- Horizontal text: use page.extract_words() which handles word grouping automatically.
- Rotated text (90° / 270°): filter page.chars where the x-scale component of the
  transformation matrix is near zero, group characters into vertical bands by x-coordinate,
  then reconstruct words by sorting top→bottom within each band.

Returns a list of ExtractedDimension dicts ready for the reconciler.
"""

import re
from dataclasses import dataclass, field
from typing import Optional
import pdfplumber

# ---------------------------------------------------------------------------
# Regex patterns for common dimension formats
# ---------------------------------------------------------------------------
_DIMENSION_PATTERNS = [
    # Diameter: ⌀12.5 ±0.1 or Φ12.5 or φ12.5
    (r"[⌀ΦφØø][\s]?(\d+(?:\.\d+)?)(?:\s*[±±]\s*(\d+(?:\.\d+)?))?", "diameter"),
    # Radius: R12.5
    (r"R[\s]?(\d+(?:\.\d+)?)(?:\s*[±±]\s*(\d+(?:\.\d+)?))?", "radius"),
    # Angle: 45° or 45.5°
    (r"(\d+(?:\.\d+)?)\s*°(?:\s*[±±]\s*(\d+(?:\.\d+)?))?", "angle"),
    # GD&T frame opener: ⊕ ⊘ ○ □ ◎ ⌖ ⊥ ∥ ∠ ↗
    (r"[⊕⊘○□◎⌖⊥∥∠↗]", "gdt"),
    # Surface roughness: Ra 3.2 or Rz 6.3
    (r"R[az]\s*(\d+(?:\.\d+)?)", "roughness"),
    # Reference dimension: (50) or (50.5)
    (r"\((\d+(?:\.\d+)?)\)", "reference"),
    # Linear with bilateral tolerance: 50 ±0.1 or 50±0.1
    (r"(\d+(?:\.\d+)?)\s*[±±]\s*(\d+(?:\.\d+)?)", "linear"),
    # Linear with unilateral tolerance: 50 +0.1/-0.0
    (r"(\d+(?:\.\d+)?)\s*\+(\d+(?:\.\d+)?)\s*/\s*-(\d+(?:\.\d+)?)", "linear"),
    # Plain numeric dimension: standalone number ≥ 2 chars like 12 / 12.5
    # Only matched last as a fallback; short single-digit numbers are often not dims
    (r"(?<!\d)(\d{2,}(?:\.\d+)?)(?!\d)", "linear"),
]

_COMPILED = [(re.compile(p, re.UNICODE), t) for p, t in _DIMENSION_PATTERNS]

# Roughness symbols that pdfplumber might encode differently
_ROUGHNESS_KEYWORDS = {"ra", "rz", "rq", "rw"}

# Words that look like dimensions but are usually not
_IGNORE_WORDS = {"a4", "a3", "iso", "din", "gb", "jis", "cad", "rev", "dwg", "date"}


@dataclass
class ExtractedDimension:
    value: str               # raw string e.g. "69.5 ±0.4"
    nominal: Optional[float]
    tolerance: Optional[str]
    dim_type: str            # matches DimensionType enum values
    view_name: Optional[str]
    source: str              # "program"
    anchor_x: Optional[float]
    anchor_y: Optional[float]
    page: int


def extract_from_pdf(pdf_path: str) -> list[ExtractedDimension]:
    """Extract all dimensions from every page of the PDF."""
    results: list[ExtractedDimension] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            results.extend(_extract_page(page, page_num))
    return results


# ---------------------------------------------------------------------------
# Per-page extraction
# ---------------------------------------------------------------------------

def _extract_page(page, page_num: int) -> list[ExtractedDimension]:
    dims: list[ExtractedDimension] = []

    # 1. Horizontal text via word grouping
    words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False)
    for w in words:
        text = w["text"].strip()
        x0, top = w["x0"], w["top"]
        _classify_and_append(text, x0, top, page_num, dims)

    # 2. Rotated text reconstruction
    rotated_words = _reconstruct_rotated(page)
    for text, x, y in rotated_words:
        _classify_and_append(text, x, y, page_num, dims)

    # Deduplicate by (value, anchor_x rounded, anchor_y rounded)
    seen: set[tuple] = set()
    unique: list[ExtractedDimension] = []
    for d in dims:
        key = (d.value, round(d.anchor_x or 0, 1), round(d.anchor_y or 0, 1))
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique


def _classify_and_append(text: str, x: float, y: float, page_num: int,
                          out: list[ExtractedDimension]) -> None:
    if not text or text.lower() in _IGNORE_WORDS:
        return
    dim = _classify(text, x, y, page_num)
    if dim:
        out.append(dim)


def _classify(text: str, x: float, y: float, page_num: int) -> Optional[ExtractedDimension]:
    text_stripped = text.strip()
    lower = text_stripped.lower()

    # Check roughness keyword prefix even without numeric match
    for kw in _ROUGHNESS_KEYWORDS:
        if lower.startswith(kw):
            nominal, tol = _parse_nominal_tol(text_stripped)
            return ExtractedDimension(
                value=text_stripped, nominal=nominal, tolerance=tol,
                dim_type="roughness", view_name=None,
                source="program", anchor_x=x, anchor_y=y, page=page_num,
            )

    for pattern, dim_type in _COMPILED:
        m = pattern.search(text_stripped)
        if m:
            nominal, tol = _parse_nominal_tol(text_stripped)
            return ExtractedDimension(
                value=text_stripped, nominal=nominal, tolerance=tol,
                dim_type=dim_type, view_name=None,
                source="program", anchor_x=x, anchor_y=y, page=page_num,
            )
    return None


def _parse_nominal_tol(text: str) -> tuple[Optional[float], Optional[str]]:
    """Return (nominal_value, tolerance_string) from a raw dimension string."""
    # bilateral ±
    m = re.search(r"(\d+(?:\.\d+)?)\s*[±±]\s*(\d+(?:\.\d+)?)", text)
    if m:
        try:
            return float(m.group(1)), f"±{m.group(2)}"
        except ValueError:
            pass

    # unilateral +x/-y
    m = re.search(r"(\d+(?:\.\d+)?)\s*\+(\d+(?:\.\d+)?)\s*/\s*-(\d+(?:\.\d+)?)", text)
    if m:
        try:
            return float(m.group(1)), f"+{m.group(2)}/-{m.group(3)}"
        except ValueError:
            pass

    # extract first bare number as nominal
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    if m:
        try:
            return float(m.group(1)), None
        except ValueError:
            pass

    return None, None


# ---------------------------------------------------------------------------
# Rotated text reconstruction
# ---------------------------------------------------------------------------
_X_BAND_TOLERANCE = 3.0  # pixels; characters within this x-range share a band


def _reconstruct_rotated(page) -> list[tuple[str, float, float]]:
    """
    Return list of (word_text, x, y) for text that is rotated ±90°.

    pdfplumber exposes each character's PDF transformation matrix via
    char['matrix'] = (a, b, c, d, e, f).
    For 90° CCW:  a≈0, b≈1  (text runs upward on page)
    For 90° CW:   a≈0, b≈-1 (text runs downward on page)
    Horizontal:   a≈1, b≈0

    We filter characters where |a| < 0.1 (i.e. not horizontal), then group
    by x-band and reconstruct words.
    """
    rotated_chars = [
        c for c in page.chars
        if abs(c.get("matrix", (1,))[0]) < 0.1   # a component near zero → rotated
    ]
    if not rotated_chars:
        return []

    # Group into x-bands
    bands: dict[float, list] = {}
    for c in rotated_chars:
        cx = c["x0"]
        matched = None
        for band_x in bands:
            if abs(cx - band_x) <= _X_BAND_TOLERANCE:
                matched = band_x
                break
        if matched is None:
            matched = cx
            bands[matched] = []
        bands[matched].append(c)

    words: list[tuple[str, float, float]] = []
    for band_x, chars in bands.items():
        # Determine rotation direction from b component of matrix
        b_vals = [c.get("matrix", (0, 0))[1] for c in chars]
        avg_b = sum(b_vals) / len(b_vals) if b_vals else 0

        if avg_b > 0:
            # 90° CCW: text runs bottom→top on page, sort descending top (larger top = lower on page)
            chars_sorted = sorted(chars, key=lambda c: -c["top"])
        else:
            # 90° CW: text runs top→bottom, sort ascending
            chars_sorted = sorted(chars, key=lambda c: c["top"])

        # Split into words on gap > 2× average char height
        if not chars_sorted:
            continue
        heights = [c.get("height", 10) for c in chars_sorted]
        avg_h = sum(heights) / len(heights)
        gap_threshold = avg_h * 2.0

        current_word_chars = [chars_sorted[0]]
        for prev_c, cur_c in zip(chars_sorted, chars_sorted[1:]):
            gap = abs(cur_c["top"] - prev_c["top"])
            if gap > gap_threshold:
                _flush_word(current_word_chars, band_x, words)
                current_word_chars = [cur_c]
            else:
                current_word_chars.append(cur_c)
        _flush_word(current_word_chars, band_x, words)

    return words


def _flush_word(chars: list, band_x: float, out: list[tuple[str, float, float]]) -> None:
    if not chars:
        return
    text = "".join(c.get("text", "") for c in chars).strip()
    if text:
        y = chars[0]["top"]
        out.append((text, band_x, y))
