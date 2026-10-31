"""Сортировка, переименование и раскладка по папкам-периодам."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .dates import PhotoInfo, scan_folder

NEEDS_REVIEW_FOLDER = "Требует_проверки"
ORIGINALS_FOLDER = "Оригиналы"


@dataclass
class PeriodRule:
    name: str
    folder_name: str
    date_from: date
    date_to: date
    prefix: str = ""


def slugify(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^\w\-_.]", "", text, flags=re.UNICODE)
    return text or "Группа"


def make_prefix(group_name: str) -> str:
    ascii_part = re.sub(r"[^A-Za-z0-9]+", "_", group_name).strip("_").upper()
    if len(ascii_part) >= 3:
        return ascii_part[:20]
    return slugify(group_name).upper()[:20] or "PHOTO"


def find_period(shot: Optional[datetime], rules: list[PeriodRule]) -> Optional[PeriodRule]:
    if not shot:
        return None
    d = shot.date()
    for rule in rules:
        if rule.date_from <= d <= rule.date_to:
            return rule
    return None


@dataclass
class SortPlanItem:
    source: Path
    target_folder: str
    target_name: str
    period_name: str
    shot_date: Optional[datetime]
    date_source: str


def build_sort_plan(
    photos: list[PhotoInfo],
    rules: list[PeriodRule],
    output_root: Path,
) -> list[SortPlanItem]:
    counters: dict[str, int] = {}
    plan: list[SortPlanItem] = []

    for info in sorted(photos, key=lambda p: (p.shot_date or datetime.max, str(p.path))):
        period = find_period(info.shot_date, rules)
        if period:
            folder = period.folder_name
            period_name = period.name
            prefix = period.prefix or make_prefix(period.name)
        else:
            folder = NEEDS_REVIEW_FOLDER
            period_name = "Требует проверки"
            prefix = "REVIEW"

        counters[folder] = counters.get(folder, 0) + 1
        idx = counters[folder]
        ext = info.path.suffix.lower()
        target_name = f"{prefix}_{idx:03d}{ext}"

        plan.append(
            SortPlanItem(
                source=info.path,
                target_folder=str(output_root / folder),
                target_name=target_name,
                period_name=period_name,
                shot_date=info.shot_date,
                date_source=info.date_source,
            )
        )
    return plan


def execute_sort_plan(plan: list[SortPlanItem], copy_mode: str = "copy") -> list[Path]:
    """copy_mode: copy | hardlink — оригиналы в исходной папке не трогаем."""
    created: list[Path] = []
    for item in plan:
        dest_dir = Path(item.target_folder)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / item.target_name
        if dest.exists():
            continue
        if copy_mode == "hardlink":
            try:
                dest.hardlink_to(item.source)
            except OSError:
                shutil.copy2(item.source, dest)
        else:
            shutil.copy2(item.source, dest)
        created.append(dest)
    return created


def backup_originals(source_folder: Path, output_root: Path) -> Path:
    dest = output_root / ORIGINALS_FOLDER
    dest.mkdir(parents=True, exist_ok=True)
    for info in scan_folder(source_folder):
        target = dest / info.path.name
        if not target.exists():
            shutil.copy2(info.path, target)
    return dest
