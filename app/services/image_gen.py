"""PDF → JPG rasterisation for web display."""

import os
import pdfplumber

RASTER_DPI = 300


def generate_drawing_images(drawing_id: int, pdf_path: str, output_dir: str) -> list[str]:
    """Rasterise each page of a PDF to JPG. Returns list of JPG filenames."""
    os.makedirs(output_dir, exist_ok=True)
    jpg_names: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            img = page.to_image(resolution=RASTER_DPI)
            jpg_name = f"page_{page_num}.jpg"
            jpg_path = os.path.join(output_dir, jpg_name)
            pil_img = img.original.convert("RGB")
            pil_img.save(jpg_path, format="JPEG", quality=85)
            jpg_names.append(jpg_name)

    return jpg_names
