"""Пути результата: исходники не трогаем, запись только в отдельную папку."""

from __future__ import annotations

from pathlib import Path

RESULT_SUFFIX = "_ФотоРетушьРезультат"


def source_root_from_path(source_path: str) -> Path:
    p = Path(source_path)
    return p if p.is_dir() else p.parent


def is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def result_root(source_path: str, output_path: str = "") -> Path:
    """Корень для всех результатов. По умолчанию — соседняя папка, не внутри исходников."""
    src_root = source_root_from_path(source_path)
    if output_path:
        out = Path(output_path).resolve()
        src_res = src_root.resolve()
        if out == src_res or is_inside(out, src_res):
            return src_res.parent / f"{src_res.name}{RESULT_SUFFIX}"
        return out
    return src_root.parent / f"{src_root.name}{RESULT_SUFFIX}"


def output_subdir(source_path: str, output_path: str, subfolder: str) -> Path:
    return result_root(source_path, output_path) / subfolder


def relative_to_source(file_path: Path, source_root: Path) -> Path:
    try:
        return file_path.resolve().relative_to(source_root.resolve())
    except ValueError:
        return Path(file_path.name)


def assert_safe_dest(src: Path, dest: Path, source_root: Path) -> None:
    """Запрет записи поверх исходника или внутрь папки с исходниками."""
    src_r = src.resolve()
    dest_r = dest.resolve()
    if src_r == dest_r:
        raise ValueError(
            f"Нельзя сохранить поверх исходника «{src.name}». "
            "Результат должен быть в отдельной папке."
        )
    src_root_r = source_root.resolve()
    if is_inside(dest_r, src_root_r):
        raise ValueError(
            f"Нельзя сохранять в папку с исходниками: {dest_r}. "
            "Используется отдельная папка результата."
        )
