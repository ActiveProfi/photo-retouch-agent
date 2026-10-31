"""Поиск точных и визуально похожих кадров для личного фотоархива."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import imagehash
from PIL import Image, ImageOps


@dataclass(frozen=True)
class DuplicateGroup:
    """Группа файлов, в которой стоит оставить один лучший кадр вручную."""

    kind: str  # exact | similar
    paths: tuple[Path, ...]


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _perceptual_hash(path: Path) -> imagehash.ImageHash:
    with Image.open(path) as image:
        return imagehash.phash(ImageOps.exif_transpose(image).convert("RGB"))


def find_duplicate_groups(
    paths: list[Path], *, similarity_threshold: int = 7
) -> tuple[list[DuplicateGroup], list[str]]:
    """Ищет точные копии и похожие кадры.

    Похожие кадры являются только кандидатами: решение об исключении всегда
    оставляется пользователю. Неподдерживаемые или повреждённые файлы попадают
    в warnings и не мешают анализу остальных фото.
    """
    exact_buckets: dict[str, list[Path]] = {}
    warnings: list[str] = []
    for path in paths:
        try:
            exact_buckets.setdefault(_file_digest(path), []).append(path)
        except OSError as exc:
            warnings.append(f"{path.name}: не удалось прочитать файл ({exc})")

    groups = [
        DuplicateGroup("exact", tuple(group))
        for group in exact_buckets.values()
        if len(group) > 1
    ]

    hashes: list[tuple[Path, imagehash.ImageHash]] = []
    exact_members = {path for group in groups for path in group.paths}
    for path in paths:
        if path in exact_members:
            continue
        try:
            hashes.append((path, _perceptual_hash(path)))
        except Exception as exc:
            warnings.append(f"{path.name}: нельзя сравнить визуально ({exc})")

    # Объединяем цепочки похожих кадров в одну группу.
    parents = list(range(len(hashes)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first, second = find(first), find(second)
        if first != second:
            parents[second] = first

    for first, (_, first_hash) in enumerate(hashes):
        for second in range(first + 1, len(hashes)):
            if first_hash - hashes[second][1] <= similarity_threshold:
                union(first, second)

    visual_buckets: dict[int, list[Path]] = {}
    for index, (path, _) in enumerate(hashes):
        visual_buckets.setdefault(find(index), []).append(path)
    groups.extend(
        DuplicateGroup("similar", tuple(group))
        for group in visual_buckets.values()
        if len(group) > 1
    )
    return groups, warnings
