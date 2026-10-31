"""Выбор папки или файла через стандартное окно Windows (ПК, флешка и т.д.)."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog
from typing import Optional

IMAGE_FILETYPES = [
    ("Фото", "*.jpg *.jpeg *.png *.webp *.tif *.tiff *.heic *.heif"),
    ("Все файлы", "*.*"),
]


def _open_dialog(dialog_func, initial_dir: Optional[str] = None) -> Optional[str]:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        kwargs = {}
        if initial_dir:
            kwargs["initialdir"] = initial_dir
        result = dialog_func(**kwargs)
    finally:
        root.destroy()
    if not result:
        return None
    return str(result)


def pick_folder(initial_dir: Optional[str] = None) -> Optional[str]:
    return _open_dialog(
        lambda **kw: filedialog.askdirectory(title="Выберите папку с фото", **kw),
        initial_dir,
    )


def pick_file(initial_dir: Optional[str] = None) -> Optional[str]:
    return _open_dialog(
        lambda **kw: filedialog.askopenfilename(
            title="Выберите фото",
            filetypes=IMAGE_FILETYPES,
            **kw,
        ),
        initial_dir,
    )
