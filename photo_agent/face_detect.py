"""Детекция лиц через MediaPipe Tasks API (mediapipe >= 1.0)."""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

logger = logging.getLogger(__name__)

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/latest/blaze_face_short_range.tflite"
)
MODEL_PATH = (Path(__file__).resolve().parent.parent / "models" / "blaze_face_short_range.tflite").resolve()
MIN_MODEL_BYTES = 100_000

_DETECTOR: Optional[vision.FaceDetector] = None
_MODEL_ERROR: Optional[str] = None


def _ensure_model() -> Path:
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    if MODEL_PATH.is_file() and MODEL_PATH.stat().st_size >= MIN_MODEL_BYTES:
        return MODEL_PATH

    if MODEL_PATH.is_file():
        MODEL_PATH.unlink(missing_ok=True)

    try:
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    except urllib.error.URLError as exc:
        raise FileNotFoundError(
            f"Не удалось скачать модель для поиска лиц. "
            f"Проверьте интернет и повторите. ({exc})"
        ) from exc

    if not MODEL_PATH.is_file() or MODEL_PATH.stat().st_size < MIN_MODEL_BYTES:
        MODEL_PATH.unlink(missing_ok=True)
        raise FileNotFoundError("Файл модели скачался не полностью. Попробуйте ещё раз.")

    return MODEL_PATH


def get_detector() -> Optional[vision.FaceDetector]:
    global _DETECTOR, _MODEL_ERROR
    if _DETECTOR is not None:
        return _DETECTOR
    if _MODEL_ERROR:
        return None
    try:
        model_path = _ensure_model()
        options = vision.FaceDetectorOptions(
            base_options=python.BaseOptions(model_asset_path=str(model_path)),
            min_detection_confidence=0.5,
        )
        _DETECTOR = vision.FaceDetector.create_from_options(options)
        return _DETECTOR
    except Exception as exc:
        _MODEL_ERROR = str(exc)
        logger.warning("Face detector unavailable: %s", exc)
        return None


def model_status() -> tuple[bool, str]:
    try:
        path = _ensure_model()
        return True, str(path)
    except Exception as exc:
        return False, str(exc)


def detect_faces_rgb(rgb: np.ndarray) -> List[Tuple[float, float, float, float]]:
    """Возвращает список bbox (x1, y1, x2, y2) в пикселях."""
    detector = get_detector()
    if detector is None:
        return []

    h, w = rgb.shape[:2]
    if rgb.dtype != np.uint8:
        rgb = rgb.astype(np.uint8)
    try:
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        result = detector.detect(mp_image)
    except Exception as exc:
        logger.warning("Face detection failed: %s", exc)
        return []

    boxes: List[Tuple[float, float, float, float]] = []
    for det in result.detections or []:
        bb = det.bounding_box
        x1 = max(0.0, bb.origin_x)
        y1 = max(0.0, bb.origin_y)
        x2 = min(float(w), x1 + bb.width)
        y2 = min(float(h), y1 + bb.height)
        if x2 > x1 and y2 > y1:
            boxes.append((x1, y1, x2, y2))
    return boxes


def build_face_mask(bgr: np.ndarray, expand: float = 0.15) -> np.ndarray:
    h, w = bgr.shape[:2]
    mask = np.zeros((h, w), dtype=np.float32)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    for x1, y1, x2, y2 in detect_faces_rgb(rgb):
        bw, bh = x2 - x1, y2 - y1
        ex1 = max(0, int(x1 - bw * expand))
        ey1 = max(0, int(y1 - bh * expand))
        ex2 = min(w, int(x2 + bw * expand))
        ey2 = min(h, int(y2 + bh * expand * 1.2))
        cv2.ellipse(
            mask,
            ((ex1 + ex2) // 2, (ey1 + ey2) // 2),
            ((ex2 - ex1) // 2, (ey2 - ey1) // 2),
            0,
            0,
            360,
            1.0,
            -1,
        )
    if mask.max() > 0:
        mask = cv2.GaussianBlur(mask, (51, 51), 0)
    return mask
