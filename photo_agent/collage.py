"""Сборка страниц и разворотов для фотокниги."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageOps

from .face_detect import detect_faces_rgb
from reportlab.lib.pagesizes import landscape
from reportlab.lib.units import cm, mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


@dataclass
class PageSpec:
    width_cm: float = 30.0
    height_cm: float = 20.0
    dpi: int = 300
    bleed_mm: float = 3.0
    gutter_mm: float = 5.0  # безопасная зона у сгиба


@dataclass
class CollageResult:
    jpg_path: Path
    pdf_path: Path
    warnings: list[str]


def _load_image(path: Path) -> Image.Image:
    return ImageOps.exif_transpose(Image.open(path).convert("RGB"))


def _face_boxes(img: Image.Image) -> list[tuple[float, float, float, float]]:
    return detect_faces_rgb(np.array(img))


def _choose_grid(n: int, images: list[Image.Image]) -> tuple[int, int]:
    portrait = sum(1 for im in images if im.height > im.width * 1.05)
    landscape_count = n - portrait
    if landscape_count >= n * 0.6:
        cols = min(3, max(2, math.ceil(math.sqrt(n))))
        rows = math.ceil(n / cols)
    elif portrait >= n * 0.6:
        cols = min(3, max(2, math.ceil(math.sqrt(n))))
        rows = math.ceil(n / cols)
    else:
        cols = min(4, max(2, math.ceil(math.sqrt(n * 1.2))))
        rows = math.ceil(n / cols)
    return cols, rows


def _fit_crop(
    img: Image.Image,
    target_w: int,
    target_h: int,
    *,
    focus: tuple[float, float] | None = None,
) -> Image.Image:
    """Заполняет ячейку, по возможности удерживая лицо в кадре."""
    iw, ih = img.size
    scale = max(target_w / iw, target_h / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
    if focus:
        focus_x, focus_y = focus[0] * scale, focus[1] * scale
        left = int(round(focus_x - target_w / 2))
        top = int(round(focus_y - target_h / 2))
        left = max(0, min(left, nw - target_w))
        top = max(0, min(top, nh - target_h))
    else:
        left = (nw - target_w) // 2
        top = (nh - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def _face_penalty(crop_box: tuple[int, int, int, int], faces: list, gutter_x: Optional[int]) -> float:
    x1, y1, x2, y2 = crop_box
    penalty = 0.0
    cx = (x1 + x2) / 2
    for fx1, fy1, fx2, fy2 in faces:
        fcx, fcy = (fx1 + fx2) / 2, (fy1 + fy2) / 2
        if not (x1 <= fcx <= x2 and y1 <= fcy <= y2):
            penalty += 2.0
        if fcy < y1 + (y2 - y1) * 0.08:
            penalty += 1.5
        if gutter_x is not None and abs(fcx - gutter_x) < (x2 - x1) * 0.06:
            penalty += 3.0
    return penalty


def build_collage(
    photo_paths: Iterable[Path],
    output_dir: Path,
    spec: PageSpec,
    page_name: str = "spread_01",
) -> CollageResult:
    paths = list(photo_paths)
    warnings: list[str] = []
    if not paths:
        raise ValueError("Нужно хотя бы одно фото для коллажа")

    output_dir.mkdir(parents=True, exist_ok=True)
    images = [_load_image(p) for p in paths]
    n = len(images)

    px_w = int(spec.width_cm / 2.54 * spec.dpi)
    px_h = int(spec.height_cm / 2.54 * spec.dpi)
    bleed_px = int(spec.bleed_mm / 25.4 * spec.dpi)
    gutter_px = int(spec.gutter_mm / 25.4 * spec.dpi)
    canvas_w = px_w + bleed_px * 2
    canvas_h = px_h + bleed_px * 2

    min_side = min(im.size[0] for im in images)
    if min_side < spec.dpi * 3:
        warnings.append(
            f"Низкое разрешение: минимальная сторона {min_side}px. Для печати {spec.dpi} dpi желательно от {spec.dpi * 4}px."
        )

    cols, rows = _choose_grid(n, images)
    gap = int(spec.dpi * 0.08)
    cell_w = (canvas_w - gap * (cols + 1)) // cols
    cell_h = (canvas_h - gap * (rows + 1)) // rows
    gutter_x = canvas_w // 2 if spec.gutter_mm > 0 else None

    page = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))

    for idx, (path, img) in enumerate(zip(paths, images)):
        row, col = divmod(idx, cols)
        x = gap + col * (cell_w + gap)
        y = gap + row * (cell_h + gap)
        faces = _face_boxes(img)
        focus = None
        if faces:
            # Координаты лиц относятся к исходнику, поэтому вычисляем центр
            # именно в нём, а не сопоставляем их с координатами страницы.
            focus = (
                sum((x1 + x2) / 2 for x1, _, x2, _ in faces) / len(faces),
                sum((y1 + y2) / 2 for _, y1, _, y2 in faces) / len(faces),
            )
        crop = _fit_crop(img, cell_w, cell_h, focus=focus)
        page.paste(crop, (x, y))

    jpg_path = output_dir / f"{page_name}.jpg"
    pdf_path = output_dir / f"{page_name}.pdf"
    page.save(jpg_path, quality=95)

    page_w_pt = (spec.width_cm + spec.bleed_mm * 2 / 10) * cm
    page_h_pt = (spec.height_cm + spec.bleed_mm * 2 / 10) * cm
    c = canvas.Canvas(str(pdf_path), pagesize=(page_w_pt, page_h_pt))
    c.drawImage(ImageReader(page), 0, 0, width=page_w_pt, height=page_h_pt)
    c.showPage()
    c.save()

    return CollageResult(jpg_path=jpg_path, pdf_path=pdf_path, warnings=warnings)
