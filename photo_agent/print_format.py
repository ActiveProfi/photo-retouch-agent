"""Подгонка фото под стандартные размеры печати с полями и вылетами."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageOps

from .caption import caption_bar_height_px, draw_caption_in_rect

# width × height в сантиметрах (классическая ориентация — вертикаль)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".heic", ".heif"}
SKIP_PRINT_DIRS = frozenset({"Печать", "Обработанные", "Оригиналы", "Требует_проверки", "Фотокнига"})

PRINT_SIZES_CM: dict[str, tuple[float, float]] = {
    "10×15 см": (10.0, 15.0),
    "15×20 см": (15.0, 20.0),
    "20×30 см": (20.0, 30.0),
    "25×30 см": (25.0, 30.0),
    "30×40 см": (30.0, 40.0),
    "30×45 см": (30.0, 45.0),
    "30×90 см": (30.0, 90.0),
}


class FitMode(str, Enum):
    COVER = "cover"  # обрезать лишнее, заполнить область
    CONTAIN = "contain"  # вписать целиком, белые поля


@dataclass
class PrintFormatSpec:
    width_cm: float
    height_cm: float
    dpi: int = 300
    margin_mm: float = 2.0  # белые поля внутри формата
    bleed_mm: float = 3.0  # вылеты за край для типографии
    fit_mode: FitMode = FitMode.COVER
    auto_orientation: bool = True
    background: tuple[int, int, int] = (255, 255, 255)


@dataclass
class PrintLayout:
    bleed_px: int
    page_w: int
    page_h: int
    margin_px: int
    inner_w: int
    inner_h: int
    photo_x: int = 0
    photo_y: int = 0
    photo_w: int = 0
    photo_h: int = 0
    caption_x: int = 0
    caption_y: int = 0
    caption_w: int = 0
    caption_bar_px: int = 0


@dataclass
class PrintFormatResult:
    image: Image.Image
    used_size_cm: tuple[float, float]
    warnings: list[str]
    layout: Optional[PrintLayout] = None


def apply_preview_guides(image: Image.Image, layout: PrintLayout, dpi: int) -> Image.Image:
    """Подсказки на предпросмотре: вылеты, граница реза, поля, зона надписи."""
    out = image.copy()
    draw = ImageDraw.Draw(out)
    lw = max(2, dpi // 150)
    b = layout.bleed_px

    draw.rectangle([0, 0, out.width - 1, out.height - 1], outline=(229, 57, 53), width=max(1, lw - 1))

    draw.rectangle(
        [b, b, b + layout.page_w - 1, b + layout.page_h - 1],
        outline=(21, 101, 192),
        width=lw,
    )

    if layout.margin_px > 0:
        px = b + layout.margin_px
        py = b + layout.margin_px
        draw.rectangle(
            [px, py, px + layout.inner_w - 1, py + layout.inner_h - 1],
            outline=(117, 117, 117),
            width=max(1, lw - 1),
        )

    if layout.caption_bar_px > 0:
        draw.rectangle(
            [
                layout.caption_x,
                layout.caption_y,
                layout.caption_x + layout.caption_w - 1,
                layout.caption_y + layout.caption_bar_px - 1,
            ],
            outline=(245, 124, 0),
            width=lw,
        )

    return out


def collect_image_files(
    folder: Path,
    *,
    recursive: bool = True,
    skip_service_dirs: bool = True,
) -> List[Path]:
    """Собирает фото для печати. По умолчанию — все подпапки, кроме служебных."""
    folder = Path(folder)
    if not folder.is_dir():
        return []

    files: List[Path] = []
    iterator = folder.rglob("*") if recursive else folder.iterdir()
    for path in iterator:
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
            continue
        if recursive and skip_service_dirs:
            rel = path.relative_to(folder)
            if len(rel.parts) > 1 and rel.parts[0] in SKIP_PRINT_DIRS:
                continue
        files.append(path)
    return sorted(files)


def count_print_breakdown(folder: Path) -> dict[str, int]:
    """Сколько файлов в корне, в подпапках и с учётом фильтра."""
    folder = Path(folder)
    all_files = collect_image_files(folder, recursive=True, skip_service_dirs=False)
    filtered = collect_image_files(folder, recursive=True, skip_service_dirs=True)
    root_only = collect_image_files(folder, recursive=False, skip_service_dirs=False)
    return {
        "all_recursive": len(all_files),
        "filtered": len(filtered),
        "root_only": len(root_only),
        "in_subfolders": max(0, len(all_files) - len(root_only)),
    }


def cm_to_px(cm: float, dpi: int) -> int:
    return max(1, int(round(cm / 2.54 * dpi)))


def mm_to_px(mm: float, dpi: int) -> int:
    return max(0, int(round(mm / 25.4 * dpi)))


def spec_from_preset(name: str, dpi: int = 300, margin_mm: float = 2.0, bleed_mm: float = 3.0) -> PrintFormatSpec:
    if name not in PRINT_SIZES_CM:
        raise ValueError(f"Неизвестный формат: {name}")
    w, h = PRINT_SIZES_CM[name]
    return PrintFormatSpec(width_cm=w, height_cm=h, dpi=dpi, margin_mm=margin_mm, bleed_mm=bleed_mm)


def _oriented_size(spec: PrintFormatSpec, img: Image.Image) -> tuple[float, float]:
    if not spec.auto_orientation:
        return spec.width_cm, spec.height_cm
    if img.width >= img.height:
        return max(spec.width_cm, spec.height_cm), min(spec.width_cm, spec.height_cm)
    return min(spec.width_cm, spec.height_cm), max(spec.width_cm, spec.height_cm)


def _fit_cover(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    iw, ih = img.size
    scale = max(target_w / iw, target_h / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
    left = (nw - target_w) // 2
    top = (nh - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def _fit_contain(img: Image.Image, target_w: int, target_h: int, bg: tuple[int, int, int]) -> Image.Image:
    iw, ih = img.size
    scale = min(target_w / iw, target_h / ih)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (target_w, target_h), bg)
    canvas.paste(resized, ((target_w - nw) // 2, (target_h - nh) // 2))
    return canvas


def format_image(img: Image.Image, spec: PrintFormatSpec, caption: Optional[str] = None) -> PrintFormatResult:
    warnings: list[str] = []
    img = ImageOps.exif_transpose(img.convert("RGB"))
    used_w_cm, used_h_cm = _oriented_size(spec, img)

    page_w = cm_to_px(used_w_cm, spec.dpi)
    page_h = cm_to_px(used_h_cm, spec.dpi)
    bleed = mm_to_px(spec.bleed_mm, spec.dpi)
    margin = mm_to_px(spec.margin_mm, spec.dpi)

    canvas_w = page_w + bleed * 2
    canvas_h = page_h + bleed * 2
    inner_w = max(1, page_w - margin * 2)
    inner_h = max(1, page_h - margin * 2)

    min_side = min(img.size)
    needed = min(inner_w, inner_h)
    if min_side < needed * 0.85:
        warnings.append(
            f"Низкое разрешение ({min_side}px). Для печати {used_w_cm:.0f}×{used_h_cm:.0f} см "
            f"при {spec.dpi} dpi желательно от {needed}px по короткой стороне."
        )

    caption_bar = caption_bar_height_px(spec.dpi) if caption and caption.strip() else 0
    photo_h = max(1, inner_h - caption_bar)
    paste_x = bleed + margin
    paste_y = bleed + margin

    if spec.fit_mode == FitMode.COVER:
        photo = _fit_cover(img, inner_w, photo_h)
    else:
        photo = _fit_contain(img, inner_w, photo_h, spec.background)

    canvas = Image.new("RGB", (canvas_w, canvas_h), spec.background)
    canvas.paste(photo, (paste_x, paste_y))

    layout = PrintLayout(
        bleed_px=bleed,
        page_w=page_w,
        page_h=page_h,
        margin_px=margin,
        inner_w=inner_w,
        inner_h=inner_h,
        photo_x=paste_x,
        photo_y=paste_y,
        photo_w=inner_w,
        photo_h=photo_h,
        caption_bar_px=caption_bar,
    )

    if caption_bar > 0:
        cap_y = paste_y + photo_h
        layout.caption_x = paste_x
        layout.caption_y = cap_y
        layout.caption_w = inner_w
        draw_caption_in_rect(
            canvas,
            caption.strip(),
            (paste_x, cap_y, paste_x + inner_w, cap_y + caption_bar),
            spec.dpi,
        )

    return PrintFormatResult(
        image=canvas,
        used_size_cm=(used_w_cm, used_h_cm),
        warnings=warnings,
        layout=layout,
    )


def format_file(
    src: Path,
    dest: Path,
    spec: PrintFormatSpec,
    caption: Optional[str] = None,
    *,
    source_root: Optional[Path] = None,
) -> PrintFormatResult:
    from .io_paths import assert_safe_dest, source_root_from_path

    root = source_root or source_root_from_path(str(src))
    assert_safe_dest(src, dest, root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as img:
        result = format_image(img, spec, caption=caption)
        save_kwargs = {"quality": 95, "optimize": True, "dpi": (spec.dpi, spec.dpi)}
        if dest.suffix.lower() in {".jpg", ".jpeg"}:
            result.image.save(dest, **save_kwargs)
        else:
            result.image.save(dest, dpi=(spec.dpi, spec.dpi))
    return result


def batch_format(
    files: List[Path],
    src_root: Path,
    out_root: Path,
    spec: PrintFormatSpec,
    suffix: str = "",
) -> tuple[list[Path], list[str]]:
    saved: list[Path] = []
    all_warnings: list[str] = []
    size_tag = f"{int(spec.width_cm)}x{int(spec.height_cm)}"
    for fpath in files:
        rel = fpath.relative_to(src_root)
        stem = rel.stem + (f"_{suffix}" if suffix else f"_{size_tag}")
        dest = out_root / rel.parent / f"{stem}.jpg"
        result = format_file(fpath, dest, spec)
        saved.append(dest)
        for w in result.warnings:
            all_warnings.append(f"{fpath.name}: {w}")
    return saved, all_warnings
