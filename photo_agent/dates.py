"""Определение даты съёмки из EXIF, имени файла или даты изменения."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import exifread
from PIL import Image
from PIL.ExifTags import TAGS

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".heic", ".heif"}


@dataclass
class PhotoInfo:
    path: Path
    shot_date: Optional[datetime]
    date_source: str  # exif | filename | mtime | unknown


def _parse_exif_datetime(value: str) -> Optional[datetime]:
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def _date_from_pillow_exif(path: Path) -> Optional[datetime]:
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return None
            for tag_id, value in exif.items():
                tag = TAGS.get(tag_id, tag_id)
                if tag in ("DateTimeOriginal", "DateTime") and isinstance(value, str):
                    return _parse_exif_datetime(value)
    except Exception:
        return None
    return None


def _date_from_exifread(path: Path) -> Optional[datetime]:
    try:
        with path.open("rb") as f:
            tags = exifread.process_file(f, stop_tag="EXIF DateTimeOriginal", details=False)
        for key in ("EXIF DateTimeOriginal", "Image DateTime"):
            if key in tags:
                parsed = _parse_exif_datetime(str(tags[key]))
                if parsed:
                    return parsed
    except Exception:
        return None
    return None


_FILENAME_DATE_PATTERNS = [
    re.compile(r"(?P<y>20\d{2})(?P<m>\d{2})(?P<d>\d{2})[_\-\s]?(?P<h>\d{2})?(?P<min>\d{2})?(?P<s>\d{2})?"),
    re.compile(r"(?P<y>20\d{2})[_\-\.](?P<m>\d{2})[_\-\.](?P<d>\d{2})"),
    re.compile(r"(?P<d>\d{2})[_\-\.](?P<m>\d{2})[_\-\.](?P<y>20\d{2})"),
]


def _date_from_filename(path: Path) -> Optional[datetime]:
    name = path.stem
    for pattern in _FILENAME_DATE_PATTERNS:
        match = pattern.search(name)
        if not match:
            continue
        groups = match.groupdict()
        try:
            y, m, d = int(groups["y"]), int(groups["m"]), int(groups["d"])
            h = int(groups.get("h") or 12)
            mi = int(groups.get("min") or 0)
            s = int(groups.get("s") or 0)
            return datetime(y, m, d, h, mi, s)
        except (ValueError, TypeError):
            continue
    return None


def get_shot_date(path: Path) -> PhotoInfo:
    path = Path(path)
    for getter, source in (
        (_date_from_pillow_exif, "exif"),
        (_date_from_exifread, "exif"),
        (_date_from_filename, "filename"),
    ):
        dt = getter(path)
        if dt:
            return PhotoInfo(path=path, shot_date=dt, date_source=source)

    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        return PhotoInfo(path=path, shot_date=mtime, date_source="mtime")
    except OSError:
        return PhotoInfo(path=path, shot_date=None, date_source="unknown")


RESULT_SUBDIR = "_ФотоРетушьРезультат"


def _skip_scan_path(path: Path) -> bool:
    """Не подхватывать служебные папки и файлы внутри папки результата."""
    return RESULT_SUBDIR in path.parts or "__MACOSX" in path.parts


def scan_folder(folder: Path) -> list[PhotoInfo]:
    """Файлы в выбранной папке и её подпапках (только внутри неё, без папки результата)."""
    folder = Path(folder)
    photos: list[PhotoInfo] = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if _skip_scan_path(path):
            continue
        photos.append(get_shot_date(path))
    return photos


def scan_sources(path: Path) -> list[PhotoInfo]:
    """Сканирует папку целиком или один выбранный файл."""
    path = Path(path)
    if path.is_file():
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            return [get_shot_date(path)]
        return []
    if path.is_dir():
        return scan_folder(path)
    return []
