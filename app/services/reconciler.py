"""
Step 3: Reconcile pdfplumber (program) results with Claude Vision (llm) results.

Rules:
- Program result is authoritative if both sources agree (same nominal value, same type).
- LLM-only dimensions are included with source="llm" (coverage supplement).
- Program-only dimensions are included with source="program".
- Duplicates within program results or within LLM results are already removed by
  their respective extractors; here we only deduplicate across the two sources.

Matching heuristic:
  Two dimensions are considered the "same" if:
    1. Their nominal values are within 0.5% of each other (or both None), AND
    2. Their dim_type matches.

Output is sorted by (page, anchor_y, anchor_x) so sequence numbers are
spatially ordered top-left to bottom-right.
"""

from dataclasses import dataclass, replace
from typing import Optional

from .extractor import ExtractedDimension


def reconcile(
    program_dims: list[ExtractedDimension],
    llm_dims: list[ExtractedDimension],
    views: list | None = None,
) -> list[ExtractedDimension]:
    """Merge two lists into a deduplicated, spatially sorted authoritative list.

    When views are provided, sorting is view-aware: dimensions are grouped by
    view in document order, then sorted by position within each view. Dims
    without a view_name are placed last.
    """

    reconciled: list[ExtractedDimension] = list(program_dims)  # program dims are primary

    for llm_dim in llm_dims:
        if not _has_match(llm_dim, reconciled):
            reconciled.append(llm_dim)

    if views:
        view_order: dict[str, tuple[int, int, float]] = {}
        for i, v in enumerate(views):
            view_order[v.name] = (v.page, i, v.bbox[1])  # (page, index, top)
        reconciled.sort(key=lambda d: (
            d.page,
            view_order.get(d.view_name or "", (d.page, 999, 999)),
            d.anchor_y if d.anchor_y is not None else 0.0,
            d.anchor_x if d.anchor_x is not None else 0.0,
        ))
    else:
        reconciled.sort(key=lambda d: (
            d.page,
            d.anchor_y if d.anchor_y is not None else 0.0,
            d.anchor_x if d.anchor_x is not None else 0.0,
        ))

    return reconciled


def _has_match(target: ExtractedDimension, pool: list[ExtractedDimension]) -> bool:
    for existing in pool:
        if existing.dim_type != target.dim_type:
            continue
        if _nominals_match(existing.nominal, target.nominal):
            return True
    return False


def _nominals_match(a: Optional[float], b: Optional[float]) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if a == 0 and b == 0:
        return True
    # Within 0.5% relative tolerance
    return abs(a - b) / max(abs(a), abs(b)) < 0.005
