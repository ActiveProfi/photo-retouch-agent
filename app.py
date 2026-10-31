"""Streamlit-приложение: сортировка, ретушь, фотокнига."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import streamlit as st
from PIL import Image

from photo_agent.collage import PageSpec, build_collage
from photo_agent.dates import scan_sources
from photo_agent.duplicates import DuplicateGroup, find_duplicate_groups
from photo_agent.enhance import EnhanceMode, enhance_file, enhance_image, load_oriented_image
from photo_agent.face_detect import model_status
from photo_agent.io_paths import is_inside, output_subdir, relative_to_source, result_root, source_root_from_path
from photo_agent.picker import pick_file, pick_folder
from photo_agent.caption import resolve_caption
from photo_agent.print_format import (
    FitMode,
    PRINT_SIZES_CM,
    apply_preview_guides,
    format_image,
    format_file,
    spec_from_preset,
)
from photo_agent.sort_photos import (
    PeriodRule,
    build_sort_plan,
    execute_sort_plan,
    make_prefix,
    slugify,
)

st.set_page_config(page_title="ФотоРетушь Агент", page_icon="📷", layout="wide")
st.title("📷 ФотоРетушь Агент")
st.caption("Сортировка · ретушь · формат под печать · фотокнига")

if "periods" not in st.session_state:
    st.session_state.periods = [
        {"name": "Шанхай 2026", "from": "2026-08-05", "to": "2026-08-10", "show_on_photo": False},
        {"name": "Токио Дисней Си", "from": "2026-08-11", "to": "2026-08-20", "show_on_photo": False},
    ]
else:
    for period in st.session_state.periods:
        period.setdefault("show_on_photo", False)

for key, default in (
    ("source_path", ""),
    ("source_kind", ""),
    ("output_path", ""),
    ("last_scan_path", ""),
    ("last_scan_kind", ""),
    ("photos", []),
    ("selected_photo_paths", []),
    ("selection_revision", 0),
    ("duplicate_groups", []),
    ("duplicate_warnings", []),
    ("print_size", "10×15 см"),
    ("print_caption", ""),
    ("print_add_date", True),
    ("steps_done", {}),
    ("step_messages", {}),
):
    if key not in st.session_state:
        st.session_state[key] = default


def _initial_dir(current: str) -> str | None:
    if not current:
        return None
    p = Path(current)
    if p.is_file():
        return str(p.parent)
    if p.is_dir():
        return str(p)
    parent = p.parent
    return str(parent) if parent.exists() else None


def _source_label(kind: str) -> str:
    return "папка" if kind == "folder" else "файл" if kind == "file" else ""


def _ensure_source_kind() -> str:
    src = st.session_state.get("source_path") or ""
    if not src:
        return ""
    kind = st.session_state.get("source_kind") or ""
    if kind in ("folder", "file"):
        return kind
    p = Path(src)
    if p.is_file():
        kind = "file"
    elif p.is_dir():
        kind = "folder"
    else:
        kind = "folder"
    st.session_state.source_kind = kind
    return kind


def _scan_and_store(path: str, kind: str) -> int:
    st.session_state.source_path = path
    st.session_state.source_kind = kind
    photos = scan_sources(Path(path))
    st.session_state.photos = photos
    st.session_state.selected_photo_paths = [str(photo.path) for photo in photos]
    # Ключ виджета выбора меняется, поэтому можно безопасно заменить набор
    # даже если повторный скан запущен с другой вкладки.
    st.session_state.selection_revision += 1
    st.session_state.duplicate_groups = []
    st.session_state.duplicate_warnings = []
    st.session_state.last_scan_path = path
    st.session_state.last_scan_kind = kind
    return len(photos)


def work_photo_paths() -> list[Path]:
    if st.session_state.get("last_scan_path") != st.session_state.get("source_path"):
        return []
    selected = st.session_state.get("selected_photo_paths") or []
    return [Path(path) for path in selected if Path(path).is_file()]


def ensure_work_photos() -> list[Path]:
    """Восстанавливает список фото: авто-скан, если папка выбрана, а список пуст."""
    src = st.session_state.get("source_path") or ""
    if not src:
        return []
    p = Path(src)
    if not p.exists():
        return []
    kind = _ensure_source_kind()
    paths = work_photo_paths()
    if paths:
        return paths
    _scan_and_store(src, kind)
    return work_photo_paths()


def _work_set_banner() -> None:
    paths = work_photo_paths()
    src = st.session_state.source_path
    if not src:
        st.warning("Слева выберите **папку** или **файл** — это будет единственный источник для всех шагов.")
        return
    if not paths:
        st.warning("Нажмите **«Сканировать»** на вкладке «Сортировка», чтобы зафиксировать список фото.")
        return
    st.success(f"**В работе: {len(paths)} фото** из `{src}` — все шаги используют только этот список.")


def _default_out_dir(subfolder: str) -> str:
    src = st.session_state.source_path
    if not src:
        return ""
    return str(output_subdir(src, st.session_state.output_path, subfolder))


def _effective_result_root() -> str:
    src = st.session_state.source_path
    if not src:
        return ""
    return str(result_root(src, st.session_state.output_path))


def _why_processing_blocked(work_files: list, out_dir: str) -> str | None:
    if not work_files:
        if not st.session_state.source_path:
            return "Слева нажмите **«Папка»** и выберите папку с фото."
        if st.session_state.get("last_scan_path") != st.session_state.get("source_path"):
            return "Нажмите **«Сканировать заново»** на вкладке **«1. Сортировка»**."
        return (
            "Фото не найдены в выбранной папке. Положите JPG/PNG в папку (можно во вложенные подпапки) "
            "и нажмите **«Сканировать заново»** на вкладке **«1. Сортировка»** или **«Обновить список фото»** ниже."
        )
    if not out_dir:
        return "Не удалось определить папку для сохранения. Выберите папку слева или исходную папку с фото."
    return None


def _set_step_complete(step_id: str, message: str, next_hint: str) -> None:
    st.session_state.steps_done[step_id] = True
    st.session_state.step_messages[step_id] = {"message": message, "next": next_hint}


def _apply_manual_selection(widget_key: str) -> None:
    st.session_state.selected_photo_paths = list(st.session_state.get(widget_key, []))


def _confirm_duplicate_choices() -> None:
    """Callback: применяет выбор до создания виджетов текущего rerun."""
    groups: list[DuplicateGroup] = st.session_state.get("duplicate_groups", [])
    kept = {
        st.session_state[f"duplicate_choice_{index}"]
        for index in range(1, len(groups) + 1)
        if st.session_state.get(f"duplicate_choice_{index}")
    }
    group_members = {str(path) for group in groups for path in group.paths}
    current = set(st.session_state.selected_photo_paths)
    selected = sorted((current - group_members) | kept)
    st.session_state.selected_photo_paths = selected
    st.session_state.selection_revision += 1
    _set_step_complete(
        "select",
        f"✅ Отбор завершён: оставлено {len(selected)} фото.",
        "Перейдите к сортировке или сразу к обработке.",
    )


def _show_step_result(step_id: str) -> None:
    info = st.session_state.step_messages.get(step_id)
    if not info:
        return
    st.success(info["message"])
    st.info(f"👉 **Следующий шаг:** {info['next']}")


def _render_step_progress() -> None:
    steps = [
        ("scan", "Выбор"),
        ("select", "Отбор"),
        ("sort", "Сортировка"),
        ("enhance", "Обработка"),
        ("print", "Печать"),
        ("book", "Фотокнига"),
    ]
    cols = st.columns(len(steps))
    for col, (sid, label) in zip(cols, steps):
        with col:
            if st.session_state.steps_done.get(sid):
                st.markdown(f"✅ **{label}**")
            else:
                st.markdown(f"⬜ {label}")


work_files = ensure_work_photos()

_render_step_progress()

tab_select, tab_sort, tab_enhance, tab_print, tab_book = st.tabs(
    ["1. Отбор", "2. Сортировка", "3. Обработка", "4. Печать", "5. Фотокнига"]
)

with st.sidebar:
    st.markdown("**Локальная ссылка:** [http://127.0.0.1:8501](http://127.0.0.1:8501)")
    st.header("Исходные фото")
    st.caption("Одна папка (или один файл) — один набор фото для всех шагов.")

    pick_col1, pick_col2 = st.columns(2)
    with pick_col1:
        if st.button("📁 Папка", use_container_width=True, key="pick_source_folder"):
            chosen = pick_folder(_initial_dir(st.session_state.source_path))
            if chosen:
                with st.spinner("Сканирую папку..."):
                    n = _scan_and_store(chosen, "folder")
                _set_step_complete(
                    "scan",
                    f"✅ Шаг 1 готов: найдено **{n}** фото.",
                    "Откройте вкладку **«1. Сортировка»** — проверьте таблицу, настройте периоды и нажмите «Подтвердить». "
                    "Или сразу **«2. Обработка»**, если сортировка не нужна.",
                )
                st.rerun()
    with pick_col2:
        if st.button("🖼️ Файл", use_container_width=True, key="pick_source_file"):
            chosen = pick_file(_initial_dir(st.session_state.source_path))
            if chosen:
                with st.spinner("Добавляю файл..."):
                    n = _scan_and_store(chosen, "file")
                _set_step_complete(
                    "scan",
                    "✅ Шаг 1 готов: **1** фото в работе.",
                    "Переходите на вкладку **«2. Обработка»** или **«3. Печать»**.",
                )
                st.rerun()

    if st.session_state.source_path:
        kind_label = _source_label(_ensure_source_kind())
        st.success(f"**Выбрано ({kind_label}):**\n\n`{st.session_state.source_path}`\n\nФото в работе: **{len(work_files)}**")
    else:
        st.warning("Папка или файл ещё не выбраны.")

    with st.expander("Или вставить путь вручную"):
        manual_source = st.text_input("Путь к папке или файлу", value=st.session_state.source_path, key="manual_source")
        if st.button("Применить путь", key="apply_manual_source"):
            p = Path(manual_source.strip())
            if p.is_dir():
                with st.spinner("Сканирую папку..."):
                    n = _scan_and_store(str(p), "folder")
                _set_step_complete("scan", f"✅ Шаг 1 готов: **{n}** фото.", "Вкладка **«1. Сортировка»** → периоды → «Подтвердить», или **«2. Обработка»**.")
                st.rerun()
            elif p.is_file():
                with st.spinner("Добавляю файл..."):
                    _scan_and_store(str(p), "file")
                _set_step_complete("scan", "✅ Шаг 1 готов: **1** фото.", "Вкладка **«2. Обработка»** или **«3. Печать»**.")
                st.rerun()
            else:
                st.error("Путь не найден.")

    st.header("Папка результата")
    if st.button("📁 Выбрать папку для результата", use_container_width=True, key="pick_output_folder"):
        chosen = pick_folder(_initial_dir(st.session_state.output_path or st.session_state.source_path))
        if chosen:
            st.session_state.output_path = chosen
            st.rerun()

    if st.session_state.source_path:
        eff = _effective_result_root()
        if st.session_state.output_path:
            out_res = Path(st.session_state.output_path).resolve()
            src_res = source_root_from_path(st.session_state.source_path).resolve()
            if out_res == src_res or is_inside(out_res, src_res):
                st.warning(
                    f"Папка результата совпадает с исходниками — сохраним **отдельно**:\n\n`{eff}`"
                )
            else:
                st.info(f"**Результат:**\n\n`{eff}`")
        else:
            st.caption(f"Папка результата не выбрана — сохранение **рядом** с исходниками:\n\n`{eff}`")
    elif st.session_state.output_path:
        st.info(f"**Результат:**\n\n`{st.session_state.output_path}`")
    else:
        st.caption("Папка результата — куда сохраняются копии, обработка и печать.")

    st.info("Исходные файлы **не изменяются** — только копии в папке результата.")

source_folder = st.session_state.source_path
output_folder = st.session_state.output_path

with tab_select:
    st.subheader("Шаг 1: отберите лучшие кадры")
    _work_set_banner()
    all_paths = [photo.path for photo in st.session_state.get("photos", [])]
    if all_paths:
        st.caption(
            f"В работе: **{len(work_files)} из {len(all_paths)}** фото. "
            "Похожие кадры не удаляются автоматически: вы сами выбираете, что оставить."
        )

        selection_key = f"manual_selected_paths_{st.session_state.selection_revision}"
        st.multiselect(
            "Какие фото оставить в работе",
            options=[str(path) for path in all_paths],
            default=st.session_state.selected_photo_paths,
            format_func=lambda path: str(Path(path).relative_to(source_root_from_path(source_folder))),
            key=selection_key,
            on_change=_apply_manual_selection,
            args=(selection_key,),
            help="Можно быстро исключить неудачные кадры, даже если они не являются дублями.",
        )
        if st.button("🔎 Найти дубли и похожие кадры", type="primary"):
            with st.status("Сравниваю фото...", expanded=True) as duplicate_status:
                groups, warnings = find_duplicate_groups(all_paths)
                st.session_state.duplicate_groups = groups
                st.session_state.duplicate_warnings = warnings
                duplicate_status.update(
                    label=f"Готово: найдено групп {len(groups)}", state="complete", expanded=False
                )

        groups: list[DuplicateGroup] = st.session_state.get("duplicate_groups", [])
        if groups:
            st.markdown("**В каждой группе выберите один кадр, который останется в работе.**")
            for index, group in enumerate(groups, start=1):
                title = "Точные копии" if group.kind == "exact" else "Визуально похожие кадры"
                with st.expander(f"{title} · группа {index} · {len(group.paths)} фото", expanded=index == 1):
                    labels = {str(path): str(path.relative_to(source_root_from_path(source_folder))) for path in group.paths}
                    choice = st.radio(
                        "Оставить", list(labels), format_func=labels.get, key=f"duplicate_choice_{index}"
                    )
                    cols = st.columns(min(4, len(group.paths)))
                    for col, path in zip(cols, group.paths):
                        with col:
                            st.image(str(path), caption=labels[str(path)], use_container_width=True)
            st.button("✅ Оставить выбранные кадры", type="primary", on_click=_confirm_duplicate_choices)
        elif st.session_state.get("duplicate_groups") == [] and st.session_state.get("duplicate_warnings"):
            st.info("Совпадений не найдено. Файлы с предупреждениями перечислены ниже.")
        for warning in st.session_state.get("duplicate_warnings", [])[:10]:
            st.warning(warning)

with tab_sort:
    st.subheader("Шаг 1–3: даты, папки, названия")
    _show_step_result("scan")
    _work_set_banner()
    col_a, col_b = st.columns([2, 1])
    with col_a:
        if st.button("Сканировать заново", type="primary"):
            if not source_folder:
                st.error("Сначала выберите папку или файл слева.")
            else:
                with st.status("⏳ Сканирую фото...", expanded=True) as scan_status:
                    n = _scan_and_store(source_folder, st.session_state.source_kind)
                    if n == 0:
                        scan_status.update(label="⚠️ Фото не найдены", state="error")
                        st.warning("В выбранной папке нет JPG/PNG (проверьте путь и вложенные подпапки).")
                    else:
                        label = f"✅ Готово: {n} фото" if n > 1 else "✅ Готово: 1 фото"
                        scan_status.update(label=label, state="complete", expanded=False)
                        _set_step_complete(
                            "scan",
                            f"✅ **Сканирование завершено.** В работе: **{n}** фото.",
                            "Справа настройте **периоды** и нажмите **«Подтвердить: создать папки»** — "
                            "или откройте вкладку **«2. Обработка»**, если сортировка не нужна.",
                        )

        if work_files:
            rows = []
            for p in st.session_state.photos:
                rows.append(
                    {
                        "Файл": p.path.name,
                        "Дата": p.shot_date.strftime("%Y-%m-%d %H:%M") if p.shot_date else "—",
                        "Источник даты": p.date_source,
                    }
                )
            st.dataframe(rows, use_container_width=True)

    with col_b:
        st.markdown("**Периоды (с — по)**")
        for i, period in enumerate(st.session_state.periods):
            with st.expander(f"Период {i + 1}: {period['name']}", expanded=i == 0):
                period["name"] = st.text_input("Название группы", value=period["name"], key=f"name_{i}")
                period["from"] = st.text_input("С даты (ГГГГ-ММ-ДД)", value=period["from"], key=f"from_{i}")
                period["to"] = st.text_input("По дату", value=period["to"], key=f"to_{i}")
                period["show_on_photo"] = st.checkbox(
                    "Указать на фото (название + дата съёмки внизу при печати)",
                    value=period.get("show_on_photo", False),
                    key=f"show_on_photo_{i}",
                )

        if st.button("+ Добавить период"):
            st.session_state.periods.append(
                {"name": "Новая группа", "from": "2026-01-01", "to": "2026-01-31", "show_on_photo": False}
            )
            st.rerun()

    sort_out = str(result_root(source_folder, output_folder)) if source_folder else ""
    if work_files and sort_out:
        rules: list[PeriodRule] = []
        for p in st.session_state.periods:
            try:
                rules.append(
                    PeriodRule(
                        name=p["name"],
                        folder_name=slugify(p["name"]),
                        date_from=date.fromisoformat(p["from"]),
                        date_to=date.fromisoformat(p["to"]),
                        prefix=make_prefix(p["name"]),
                    )
                )
            except ValueError:
                st.warning(f"Неверная дата в периоде «{p['name']}»")

        if rules:
            plan = build_sort_plan(st.session_state.photos, rules, Path(sort_out))
            st.caption(f"Копии будут в отдельной папке: `{sort_out}` (исходники не трогаем).")
            preview = [
                {
                    "Период": item.period_name,
                    "Новое имя": item.target_name,
                    "Папка": Path(item.target_folder).name,
                    "Дата": item.shot_date.strftime("%Y-%m-%d") if item.shot_date else "—",
                }
                for item in plan[:200]
            ]
            st.markdown("**Предпросмотр (первые 200)**")
            st.dataframe(preview, use_container_width=True)

            if st.button("✅ Подтвердить: создать папки и скопировать", type="primary"):
                with st.status("⏳ Создаю папки и копирую фото...", expanded=True) as sort_status:
                    created = execute_sort_plan(plan, copy_mode="copy")
                    sort_status.update(
                        label=f"✅ Скопировано {len(created)} фото",
                        state="complete",
                        expanded=False,
                    )
                st.session_state.sorted_files = [str(p) for p in created]
                _set_step_complete(
                    "sort",
                    f"✅ **Сортировка завершена.** Скопировано **{len(created)}** фото в `{sort_out}`.",
                    "Откройте вкладку **«2. Обработка»** → нажмите **«Обработать все фото»**.",
                )

    _show_step_result("sort")

with tab_enhance:
    st.subheader("Шаг 4: лёгкая обработка")
    _show_step_result("enhance")
    _work_set_banner()

    model_ok, model_info = model_status()
    if not model_ok:
        st.warning(f"Модель для ретуши лица: {model_info}. Будут только свет и резкость.")

    mode_label = st.radio(
        "Режим",
        options=["Без ретуши", "Лёгкая (рекомендуется)", "Умеренная"],
        index=1,
        horizontal=True,
    )
    mode_map = {
        "Без ретуши": EnhanceMode.NONE,
        "Лёгкая (рекомендуется)": EnhanceMode.LIGHT,
        "Умеренная": EnhanceMode.MODERATE,
    }
    mode = mode_map[mode_label]

    enhance_out = _default_out_dir("Обработанные")
    if enhance_out:
        st.caption(f"**Куда сохраняем (исходники не трогаем):** `{enhance_out}`")

    block_reason = _why_processing_blocked(work_files, enhance_out)
    can_process = block_reason is None
    if block_reason:
        st.warning(f"**Кнопка пока неактивна:** {block_reason}")

    if st.button(
        f"✅ Обработать все фото ({len(work_files)})" if work_files else "✅ Обработать все фото",
        type="primary",
        disabled=not can_process,
        key="enhance_all_btn",
    ):
        out_dir = Path(enhance_out)
        src_root = source_root_from_path(source_folder)
        with st.status("⏳ Обрабатываю фото...", expanded=True) as enhance_status:
            progress = st.progress(0, text="Начинаю...")
            failed: list[str] = []
            for i, fpath in enumerate(work_files):
                rel = relative_to_source(fpath, src_root)
                dest = out_dir / rel
                try:
                    enhance_file(fpath, dest, mode, source_root=src_root)
                except Exception as exc:
                    failed.append(f"{fpath.name}: {exc}")
                progress.progress((i + 1) / len(work_files), text=f"Обработано {i + 1} из {len(work_files)}")
            progress.empty()
            enhance_status.update(
                label=f"✅ Готово: {len(work_files) - len(failed)} из {len(work_files)} фото",
                state="complete" if not failed else "error",
                expanded=False,
            )
        for error in failed[:10]:
            st.warning(f"Не обработано: {error}")
        _set_step_complete(
            "enhance",
            f"✅ **Обработка завершена.** {len(work_files)} фото сохранены в `{out_dir}`.",
            "Откройте вкладку **«3. Печать»** → выберите размер → **«Подогнать все фото»**.",
        )
        _show_step_result("enhance")

    st.divider()
    st.markdown("**Предпросмотр «до / после»**")
    if work_files:
        preview_files = work_files[:20]
        sample_path = st.selectbox(
            "Выберите фото из текущего набора",
            preview_files,
            format_func=lambda path: str(path.relative_to(source_root_from_path(source_folder))),
            key="enhance_preview_pick",
        )

        if sample_path.is_file():
            before = load_oriented_image(sample_path)
            after, rep = enhance_image(before.copy(), mode)
            c1, c2 = st.columns(2)
            with c1:
                st.image(before, caption="До", use_container_width=True)
            with c2:
                st.image(after, caption=f"После ({mode.value})", use_container_width=True)

with tab_print:
    st.subheader("Шаг 5: формат под печать")
    _show_step_result("print")
    _work_set_banner()

    print_size = st.selectbox(
        "Размер печати",
        options=list(PRINT_SIZES_CM.keys()),
        index=list(PRINT_SIZES_CM.keys()).index(st.session_state.print_size)
        if st.session_state.print_size in PRINT_SIZES_CM
        else 0,
        key="print_size_select",
    )
    st.session_state.print_size = print_size

    col_p1, col_p2, col_p3 = st.columns(3)
    with col_p1:
        print_dpi = st.number_input("DPI", min_value=150, max_value=600, value=300, step=50, key="print_dpi")
    with col_p2:
        print_margin = st.number_input("Поля, мм", min_value=0.0, max_value=20.0, value=2.0, step=0.5, key="print_margin")
    with col_p3:
        print_bleed = st.number_input("Вылеты, мм", min_value=0.0, max_value=10.0, value=3.0, step=0.5, key="print_bleed")

    fit_label = st.radio(
        "Как вписать фото",
        options=["Обрезать по размеру (рекомендуется)", "Вписать целиком с белыми полями"],
        horizontal=True,
        key="print_fit",
    )
    fit_mode = FitMode.COVER if "Обрезать" in fit_label else FitMode.CONTAIN
    auto_orient = st.checkbox("Автоповорот вертикаль/горизонталь", value=True)

    st.markdown("**Надпись внизу фото**")
    print_caption = st.text_input(
        "Текст (если период не подошёл)",
        value=st.session_state.print_caption,
        placeholder="Токио Дисней Си",
        key="print_caption_input",
    )
    st.session_state.print_caption = print_caption
    print_add_date = st.checkbox("Добавить дату съёмки", value=st.session_state.print_add_date, key="print_add_date_cb")
    st.session_state.print_add_date = print_add_date
    use_period_captions = st.checkbox("Брать надписи из периодов с галочкой «Указать на фото»", value=True)

    spec = spec_from_preset(print_size, dpi=int(print_dpi), margin_mm=print_margin, bleed_mm=print_bleed)
    spec.fit_mode = fit_mode
    spec.auto_orientation = auto_orient

    print_out = _default_out_dir("Печать")
    if print_out:
        st.caption(f"**Куда сохраняем (исходники не трогаем):** `{print_out}`")

    st.markdown(f"**Фото для печати:** {len(work_files)}")

    col_rescan, _ = st.columns([1, 3])
    with col_rescan:
        if st.button("🔄 Обновить список фото", key="print_rescan_btn"):
            if source_folder:
                with st.spinner("Сканирую..."):
                    n = _scan_and_store(source_folder, _ensure_source_kind())
                st.success(f"Найдено **{n}** фото.")
                st.rerun()
            else:
                st.error("Сначала выберите папку слева.")

    block_print = _why_processing_blocked(work_files, print_out)
    can_print = block_print is None
    if block_print:
        st.warning(f"**Кнопка пока неактивна:** {block_print}")

    if st.button(
        f"✅ Подогнать все фото под {print_size} ({len(work_files)})" if work_files else f"✅ Подогнать все фото",
        type="primary",
        disabled=not can_print,
        key="print_all_btn",
    ):
        size_folder = Path(print_out) / print_size.replace(" ", "_").replace("×", "x")
        src_root = source_root_from_path(source_folder)
        size_tag = print_size.replace(" ", "").replace("×", "x")
        warn_seen: set[str] = set()
        with st.status("⏳ Подгоняю под формат печати...", expanded=True) as print_status:
            progress = st.progress(0, text="Начинаю...")
            failed: list[str] = []
            for i, fpath in enumerate(work_files):
                rel = relative_to_source(fpath, src_root)
                dest = size_folder / rel.parent / f"{rel.stem}_{size_tag}.jpg"
                caption = resolve_caption(
                    fpath,
                    st.session_state.periods,
                    manual_text=print_caption,
                    add_date_if_manual=print_add_date,
                    use_period_labels=use_period_captions,
                )
                try:
                    result = format_file(fpath, dest, spec, caption=caption, source_root=src_root)
                    for w in result.warnings:
                        warn_seen.add(f"{fpath.name}: {w}")
                except Exception as exc:
                    failed.append(f"{fpath.name}: {exc}")
                progress.progress((i + 1) / len(work_files), text=f"Готово {i + 1} из {len(work_files)}")
            progress.empty()
            print_status.update(
                label=f"✅ Готово: {len(work_files) - len(failed)} из {len(work_files)} фото",
                state="complete" if not failed else "error",
                expanded=False,
            )
        _set_step_complete(
            "print",
            f"✅ **Печать готова.** {len(work_files)} файлов в `{size_folder}`.",
            "Можно отдать файлы в типографию. Для коллажа — вкладка **«4. Фотокнига»**.",
        )
        _show_step_result("print")
        for w in list(warn_seen)[:5]:
            st.warning(w)
        for error in failed[:10]:
            st.warning(f"Не подготовлено к печати: {error}")

    st.divider()
    st.markdown("**Предпросмотр — как будет выглядеть напечатанное фото**")
    if work_files:
        preview_files = work_files[:20]
        src_root = source_root_from_path(source_folder)

        def _print_preview_label(path: Path) -> str:
            try:
                return str(path.relative_to(src_root))
            except ValueError:
                return path.name

        pick_path = st.selectbox(
            "Фото из текущего набора",
            preview_files,
            format_func=_print_preview_label,
            key="print_preview_pick",
        )
        if pick_path.is_file():
            sample_caption = resolve_caption(
                pick_path,
                st.session_state.periods,
                manual_text=print_caption,
                add_date_if_manual=print_add_date,
                use_period_labels=use_period_captions,
            )
            with Image.open(pick_path) as raw:
                preview = format_image(raw, spec, caption=sample_caption)
            preview_img = apply_preview_guides(preview.image, preview.layout, int(print_dpi)) if preview.layout else preview.image
            st.image(preview_img, use_container_width=True)
            st.caption("🔴 вылеты · 🔵 граница реза · 🟠 надпись внутри реза — так будет на отпечатке")

with tab_book:
    st.subheader("Шаг 6: коллаж / разворот для фотокниги")
    _show_step_result("book")
    _work_set_banner()

    selected_names = st.text_area(
        "Имена файлов через запятую (пусто — первые N из текущего набора)",
        placeholder="PHOTO_001.jpg, PHOTO_002.jpg",
    )
    n_photos = st.number_input("Сколько фото на разворот", min_value=1, max_value=30, value=15)
    width_cm = st.number_input("Ширина, см", value=30.0)
    height_cm = st.number_input("Высота, см", value=20.0)
    dpi = st.number_input("DPI для печати", value=300, step=50)
    bleed = st.number_input("Вылеты, мм", value=3.0)

    if st.button("Создать разворот", disabled=not work_files):
        if selected_names.strip():
            names = {n.strip() for n in selected_names.split(",") if n.strip()}
            paths = [p for p in work_files if p.name in names]
        else:
            paths = work_files[: int(n_photos)]

        if not paths:
            st.error("Не найдено ни одного фото из текущего набора.")
        else:
            with st.status("⏳ Собираю разворот...", expanded=True) as book_status:
                spec = PageSpec(width_cm=width_cm, height_cm=height_cm, dpi=int(dpi), bleed_mm=bleed)
                out_dir = Path(_default_out_dir("Фотокнига") or output_folder or ".")
                result = build_collage(paths, out_dir, spec)
                book_status.update(label="✅ Разворот готов", state="complete", expanded=False)
            _set_step_complete(
                "book",
                f"✅ **Фотокнига готова.** JPG и PDF сохранены в `{out_dir}`.",
                "Все шаги выполнены! Файлы можно отправлять в печать.",
            )
            _show_step_result("book")
            st.image(str(result.jpg_path), use_container_width=True)
            st.write(f"PDF: `{result.pdf_path}`")
