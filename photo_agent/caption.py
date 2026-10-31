"""Надпись внизу фото для печати (внутри области реза)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from .dates import get_shot_date

FONT_CANDIDATES = (
    Path(r"C:\Windows\Fonts\segoeui.ttf"),
    Path(r"C:\Windows\Fonts\arial.ttf"),
    Path(r"C:\Windows\Fonts\calibri.ttf"),
)


def _load_font(size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if path.is_file():
            return ImageFont.truetype(str(path), size_px)
    return ImageFont.load_default()


def caption_bar_height_px(dpi: int, bar_height_mm: float = 7.0) -> int:
    return max(24, int(round(bar_height_mm / 25.4 * dpi)))


def draw_caption_in_rect(
    canvas: Image.Image,
    text: str,
    box: tuple[int, int, int, int],
    dpi: int,
    *,
    bar_color: tuple[int, int, int] = (255, 255, 255),
    text_color: tuple[int, int, int] = (40, 40, 40),
    padding_mm: float = 1.0,
) -> None:
    """Рисует надпись внутри заданного прямоугольника на холсте (без увеличения размера)."""
    if not text or not text.strip():
        return

    text = text.strip()
    x1, y1, x2, y2 = box
    bar_w = max(1, x2 - x1)
    bar_h = max(1, y2 - y1)
    pad = max(4, int(round(padding_mm / 25.4 * dpi)))

    draw = ImageDraw.Draw(canvas)
    draw.rectangle([x1, y1, x2 - 1, y2 - 1], fill=bar_color)

    font_size = max(12, min(int(bar_h * 0.52), int(bar_w * 0.045)))
    font = _load_font(font_size)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    while tw > bar_w - pad * 2 and font_size > 10:
        font_size -= 1
        font = _load_font(font_size)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]

    th = bbox[3] - bbox[1]
    tx = x1 + max(pad, (bar_w - tw) // 2)
    ty = y1 + (bar_h - th) // 2
    draw.text((tx, ty), text, fill=text_color, font=font)


def find_period_for_date(shot: Optional[datetime], periods: list[dict]) -> Optional[dict]:
    if not shot:
        return None
    d = shot.date()
    for period in periods:
        try:
            d_from = date.fromisoformat(period["from"])
            d_to = date.fromisoformat(period["to"])
        except (ValueError, KeyError):
            continue
        if d_from <= d <= d_to:
            return period
    return None


def resolve_caption(
    photo_path: Path,
    periods: list[dict],
    manual_text: str = "",
    add_date_if_manual: bool = False,
    use_period_labels: bool = True,
) -> Optional[str]:
    """Собирает текст подписи: период с галочкой или ручная надпись."""
    info = get_shot_date(photo_path)

    if use_period_labels:
        period = find_period_for_date(info.shot_date, periods)
        if period and period.get("show_on_photo"):
            text = period.get("name", "").strip()
            if text and info.shot_date:
                return f"{text} · {info.shot_date.strftime('%d.%m.%Y')}"
            return text or None

    manual = manual_text.strip()
    if manual:
        if add_date_if_manual and info.shot_date:
            return f"{manual} · {info.shot_date.strftime('%d.%m.%Y')}"
        return manual

    return None
