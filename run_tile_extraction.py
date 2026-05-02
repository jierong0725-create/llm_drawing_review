"""
临时脚本：对指定 PDF 运行 tile-based dimension extraction 流水线。

Usage:
    python run_tile_extraction.py /path/to/pdf

输出：
    - excluded regions
    - pdfplumber 提取的尺寸（过滤后）
    - LLM tile 提取的尺寸（过滤后）
    - reconcile 合并后的最终尺寸列表
"""

import sys
import os
from pprint import pprint

# 确保能找到 app 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.analyzer import detect_excluded_regions, extract_dimensions_tiled
from app.services.extractor import extract_from_pdf, filter_excluded
from app.services.reconciler import reconcile


def main(pdf_path: str):
    if not os.path.isfile(pdf_path):
        print(f"[ERROR] 文件不存在: {pdf_path}")
        sys.exit(1)

    print(f"{'='*60}")
    print(f"  PDF: {pdf_path}")
    print(f"{'='*60}\n")

    # Phase 1: 检测排除区域（标题栏、公差注释等）
    print("▸ Phase 1: detect_excluded_regions ...")
    excluded = detect_excluded_regions(pdf_path)
    print(f"  排除区域: {len(excluded)}")
    for e in excluded:
        print(f"    - {e.region_type}: {e.bbox}")
    print()

    # Phase 2a: pdfplumber 文本提取 + 过滤排除区域
    print("▸ Phase 2a: pdfplumber text extraction ...")
    program_dims = extract_from_pdf(pdf_path)
    print(f"  原始提取: {len(program_dims)} 个")
    program_dims = filter_excluded(program_dims, excluded, is_pixels=False)
    print(f"  过滤后:   {len(program_dims)} 个")
    for d in program_dims[:20]:
        print(f"    [{d.dim_type}] {d.value}  @ ({d.anchor_x:.1f}, {d.anchor_y:.1f})")
    if len(program_dims) > 20:
        print(f"    ... 还有 {len(program_dims) - 20} 个")
    print()

    # Phase 2b: Tile-based LLM 提取（full-resolution, 并行）
    print("▸ Phase 2b: tile-based LLM extraction ...")
    print("  (调用 Claude Vision，可能需要一些时间...)")
    llm_dims = extract_dimensions_tiled(pdf_path, excluded)
    print(f"  LLM 提取: {len(llm_dims)} 个")
    for d in llm_dims[:20]:
        print(f"    [{d.dim_type}] {d.value}  @ ({d.anchor_x:.1f}, {d.anchor_y:.1f})")
    if len(llm_dims) > 20:
        print(f"    ... 还有 {len(llm_dims) - 20} 个")
    print()

    # Phase 3: Reconcile
    print("▸ Phase 3: reconcile ...")
    final_dims = reconcile(program_dims, llm_dims, views=None)
    print(f"  最终合并: {len(final_dims)} 个")
    for i, d in enumerate(final_dims, 1):
        print(f"    {i:3d}. [{d.source:7s}] [{d.dim_type:10s}] {d.value}")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python run_tile_extraction.py <pdf_path>")
        sys.exit(1)
    main(sys.argv[1])
