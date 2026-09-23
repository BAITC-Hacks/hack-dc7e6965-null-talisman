"""Explicit import preparation inside the sidebar."""
import hashlib
import json

import pandas as pd
import streamlit as st

from app.backend import inspect_partner_files, load_partner_files
from app.partner_import import BRANDS, KINDS, missing_reports


def render_import(files, today):
    reports = inspect_partner_files(files)
    st.success(f"Распознано листов: {len(reports)}")
    with st.expander("Состав загруженных отчётов", expanded=True):
        st.dataframe(pd.DataFrame([{"Файл": r.filename, "Лист": r.sheet, "Тип": KINDS[r.kind],
                                    "Поставщик": BRANDS[r.brand]} for r in reports]), hide_index=True)
    missing = missing_reports(reports)
    if missing:
        st.info("Для расчёта добавьте: " + "; ".join(missing) + ". Выберите весь набор файлов вместе.")
    st.caption("Сводный расчёт по всем складам. Используются завершённые месяцы. Клиенты, периоды отсутствия и BOM в этих отчётах не заданы.")
    settings = {}
    with st.expander("Настройки импорта", expanded=True):
        for brand in sorted({r.brand for r in reports}):
            st.write(BRANDS[brand])
            settings[brand] = {
                "lead_time_days": st.number_input("Срок поставки, дней", min_value=1, max_value=365, value=14, key=f"lead_{brand}"),
                "order_cycle_days": st.number_input("Цикл заказа, дней", min_value=1, max_value=365, value=14, key=f"cycle_{brand}"),
            }
        st.caption("14 дней — начальная настройка, а не значение из Excel. Укажите реальные сроки. ИЭК: берётся последний месячный остаток; Systeme: свободный остаток из сводного отчёта, если он загружен. Движения после среза не учитываются.")
        st.caption("Пустые количества = 0. Без MOQ: кратность 1, минимум 0. Единицы покупки/хранения не пересчитываются. Отчёт сезонности используется справочно.")
        settings["confirmed"] = st.checkbox("Принимаю настройки и использование указанного среза остатков", key="partner_confirmed")
    digest = hashlib.sha256(json.dumps([settings, today], sort_keys=True).encode())
    for name, content in files:
        digest.update(name.encode())
        digest.update(content)
    signature = digest.hexdigest()
    if st.button("Подготовить данные", disabled=bool(missing) or not settings["confirmed"], type="primary"):
        # Never keep a usable prior import if replacement fails.
        st.session_state.pop("partner_prepared", None)
        with st.spinner("Читаем отчёты и проверяем данные…"):
            data, warnings = load_partner_files(files, settings, today)
        st.session_state.partner_prepared = (signature, data, warnings)
    prepared = st.session_state.get("partner_prepared")
    if not prepared or prepared[0] != signature:
        st.info("После выбора файлов и настроек нажмите «Подготовить данные».")
        return None, settings
    data, warnings = prepared[1:]
    st.success(f"Подготовлено: {len(data['products'])} товаров, {len(data['stock'])} остатков, {len(data['sales'])} строк месячной истории.")
    with st.expander("Источники и ограничения расчёта", expanded=True):
        for warning in warnings:
            st.warning(warning)
    return data, settings
