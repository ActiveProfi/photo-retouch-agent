"""Лёгкая обработка без генеративных моделей: свет, шум, резкость, мягкая кожа."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageOps

from .face_detect import build_face_mask, get_detector, model_status
from .io_paths import assert_safe_dest, source_root_from_path


class EnhanceMode(str, Enum):
    NONE = "none"
    LIGHT = "light"
    MODERATE = "moderate"


def load_oriented_image(path: Path) -> Image.Image:
    """Открывает фото в той ориентации, как на телефоне/камере (с учётом EXIF)."""
    with Image.open(path) as img:
        return ImageOps.exif_transpose(img)


def _pil_to_bgr(img: Image.Image) -> np.ndarray:
    rgb = np.array(img.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _bgr_to_pil(bgr: np.ndarray) -> Image.Image:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def _apply_global_adjustments(img: Image.Image, strength: float) -> Image.Image:
    img = ImageOps.autocontrast(img, cutoff=int(1 + strength))
    img = ImageEnhance.Brightness(img).enhance(1.0 + 0.04 * strength)
    img = ImageEnhance.Color(img).enhance(1.0 + 0.06 * strength)
    img = ImageEnhance.Contrast(img).enhance(1.0 + 0.05 * strength)
    img = ImageEnhance.Sharpness(img).enhance(1.0 + 0.15 * strength)
    return img


def _denoise(bgr: np.ndarray, strength: float) -> np.ndarray:
    h = int(3 + 4 * strength)
    return cv2.fastNlMeansDenoisingColored(bgr, None, h, h, 7, 21)


def _skin_smooth(bgr: np.ndarray, mask: np.ndarray, level: float) -> np.ndarray:
    if mask.max() < 0.01 or level <= 0:
        return bgr
    d = int(5 + 3 * level)
    sigma = 20 + 15 * level
    smooth = cv2.bilateralFilter(bgr, d=d, sigmaColor=sigma, sigmaSpace=sigma)
    m = mask[:, :, np.newaxis]
    blend = 0.25 + 0.35 * level
    out = bgr.astype(np.float32) * (1 - m * blend) + smooth.astype(np.float32) * (m * blend)
    return np.clip(out, 0, 255).astype(np.uint8)


def _hair_edge_soften(bgr: np.ndarray, mask: np.ndarray, level: float) -> np.ndarray:
    """Очень слабое сглаживание по краю маски — не «причёсывает», только убирает жёсткий пуш."""
    if mask.max() < 0.01 or level <= 0:
        return bgr
    edge = cv2.Canny((mask * 255).astype(np.uint8), 50, 150)
    edge = cv2.dilate(edge, np.ones((3, 3), np.uint8), iterations=1)
    edge = cv2.GaussianBlur(edge.astype(np.float32), (9, 9), 0) / 255.0
    if edge.max() < 0.01:
        return bgr
    soft = cv2.bilateralFilter(bgr, 5, 40, 40)
    m = edge[:, :, np.newaxis] * (0.15 * level)
    out = bgr.astype(np.float32) * (1 - m) + soft.astype(np.float32) * m
    return np.clip(out, 0, 255).astype(np.uint8)


def enhance_image(img: Image.Image, mode: EnhanceMode = EnhanceMode.LIGHT) -> Tuple[Image.Image, dict]:
    """Возвращает обработанное изображение и краткий отчёт."""
    report = {"mode": mode.value, "faces_found": 0}

    if mode == EnhanceMode.NONE:
        strength = 0.6
    elif mode == EnhanceMode.LIGHT:
        strength = 1.0
    else:
        strength = 1.4

    img = ImageOps.exif_transpose(img)
    adjusted = _apply_global_adjustments(img, strength)
    bgr = _pil_to_bgr(adjusted)
    bgr = _denoise(bgr, min(strength, 1.2))

    if mode != EnhanceMode.NONE:
        ok, model_info = model_status()
        report["face_model_ok"] = ok
        if not ok:
            report["face_model_note"] = model_info
        elif get_detector() is None:
            report["face_model_ok"] = False
            report["face_model_note"] = "Модель лиц недоступна — применены только свет и резкость."
        else:
            mask = build_face_mask(bgr)
            report["faces_found"] = int(mask.max() > 0.01)
            skin_level = 0.4 if mode == EnhanceMode.LIGHT else 0.75
            hair_level = 0.3 if mode == EnhanceMode.LIGHT else 0.5
            bgr = _skin_smooth(bgr, mask, skin_level)
            bgr = _hair_edge_soften(bgr, mask, hair_level)

    return _bgr_to_pil(bgr), report


def enhance_file(
    src: Path,
    dest: Path,
    mode: EnhanceMode = EnhanceMode.LIGHT,
    *,
    source_root: Path | None = None,
) -> dict:
    root = source_root or source_root_from_path(str(src))
    assert_safe_dest(src, dest, root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as img:
        out, report = enhance_image(img, mode)
        save_kwargs = {"quality": 95, "optimize": True}
        if dest.suffix.lower() in {".jpg", ".jpeg"}:
            out.save(dest, **save_kwargs)
        else:
            out.save(dest)
    report["source"] = str(src)
    report["dest"] = str(dest)
    return report
