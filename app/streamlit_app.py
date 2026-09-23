"""Run from the repository root: streamlit run app/streamlit_app.py."""

import hashlib
import json
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from app.backend import calculate, demo_files, load_files, series
from app.charts import demand_chart
from app.orders import approve, csv_bytes, edited_order, fingerprint, xlsx_bytes

st.set_page_config(page_title="Заказы поставщикам · Null Talisman", page_icon="📦", layout="wide")
LOG = logging.getLogger(__name__)
if st.session_state.get("ui_page") != "orders" and "result" in st.session_state:
    st.session_state.generation = st.session_state.get("generation", 0) + 1
    st.session_state.editor_inputs = {}
st.session_state.ui_page = "orders"
URGENCY = {"critical": "🔴 Критично", "high": "🟠 Высокая", "normal": "🟢 Планово"}
CONFIDENCE = {"high": "Высокая", "medium": "Средняя", "low": "Низкая"}


def show_error(exc):
    LOG.warning("UI operation failed", exc_info=True)
    st.warning(str(exc) if isinstance(exc, ValueError) else "Не удалось выполнить действие. Проверьте файлы и доступность расчётного модуля; подробности — в журнале приложения.")


def signature(files, params):
    digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode())
    for name, content in files:
        digest.update(name.encode())
        digest.update(content)
    return digest.hexdigest()


def downloads(frame, prefix):
    try:
        excel, csv = xlsx_bytes(frame), csv_bytes(frame)
    except Exception as exc:
        show_error(exc)
        return
    left, right = st.columns(2)
    left.download_button("Скачать XLSX", excel, f"orders_{prefix}.xlsx",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"xlsx_{prefix}")
    right.download_button("Скачать CSV", csv, f"orders_{prefix}.csv", "text/csv", key=f"csv_{prefix}")


def position_card(frame, data, key):
    labels = [f"{row.sku} · {row['name']} · {row.warehouse}" for _, row in frame.iterrows()]
    selected = st.selectbox("Подробнее по позиции", range(len(frame)), format_func=lambda i: labels[i], key=f"detail_{key}")
    row = frame.iloc[selected]
    st.markdown(f"#### {row['name']}")
    st.write(row["explanation"])
    columns = st.columns(4)
    columns[0].metric("Прогноз на горизонт", f"{row.forecast_horizon:,.0f} шт.")
    columns[1].metric("Страховой запас", f"{row.get('safety_stock', 0):,.0f} шт.")
    cover = row.get("days_of_cover")
    columns[2].metric("Остатка хватит", f"{cover:.1f} дн." if pd.notna(cover) else "Нет данных")
    columns[3].metric("Доверие к прогнозу", CONFIDENCE.get(row.confidence, row.confidence))
    if bool(row.get("transit_overdue", False)):
        st.warning("Есть просроченная поставка. Уточните ETA у поставщика перед утверждением.")
    if row.get("flags"):
        st.caption(f"Особенности расчёта: {row['flags']}")
    try:
        st.plotly_chart(demand_chart(series(data, row.sku, row.warehouse)), width="stretch", key=f"chart_{key}")
        st.caption("Серый — факт, синий — очищенный спрос, пунктир — прогноз. Красные точки — разовый сверхобъём; оранжевый фон — месяцы отсутствия товара.")
    except Exception as exc:
        show_error(exc)


st.caption("NULL TALISMAN / ЗАКУПКИ")
st.title("Заказы поставщикам")
st.write("Рассчитайте пополнение склада, проверьте обоснование и утвердите заказ.")

saved = st.session_state.get("calculation_params", {})
data, files = None, ()
with st.sidebar:
    st.header("Параметры расчёта")
    source_options = ["Демонстрационные данные", "Загрузить файлы"]
    source = st.radio("Источник данных", source_options,
                      index=source_options.index(st.session_state.get("saved_source", source_options[0])))
    st.session_state.saved_source = source
    if source == "Загрузить файлы":
        st.caption("Отдельный CSV или XLSX для каждой таблицы. Имена: sales, stock, products, suppliers; дополнительно in_transit, stockouts, growth, bom.")
        uploads = st.file_uploader("Входные таблицы", type=["csv", "xlsx"], accept_multiple_files=True,
                                   key=f"uploads_{st.session_state.get('upload_version', 0)}")
        if uploads:
            st.session_state.saved_uploads = tuple(sorted((upload.name, upload.getvalue()) for upload in uploads))
        files = st.session_state.get("saved_uploads", ())
        if files:
            st.caption("Используются: " + ", ".join(name for name, _ in files))
            if st.button("Очистить загруженные файлы"):
                st.session_state.pop("saved_uploads", None)
                st.session_state.upload_version = st.session_state.get("upload_version", 0) + 1
                st.rerun()
    else:
        try:
            files = demo_files()
        except Exception as exc:
            show_error(exc)
    if files:
        try:
            data, warnings = load_files(files)
            for warning in warnings:
                st.warning(str(warning))
        except Exception as exc:
            show_error(exc)
    warehouses = sorted(data["stock"]["warehouse"].dropna().astype(str).unique()) if data else []
    categories = sorted(data["products"]["category"].dropna().astype(str).unique()) if data else []
    warehouse_options, category_options = [None, *warehouses], [None, *categories]
    warehouse = st.selectbox("Склад", warehouse_options,
                             index=warehouse_options.index(saved.get("warehouse")) if saved.get("warehouse") in warehouse_options else 0,
                             format_func=lambda value: value or "Все склады")
    category = st.selectbox("Категория", category_options,
                            index=category_options.index(saved.get("category")) if saved.get("category") in category_options else 0,
                            format_func=lambda value: value or "Все категории")
    service = st.select_slider("Уровень сервиса", options=[.90, .95, .98], value=saved.get("service_level", .95), format_func=lambda value: f"{value:.0%}")
    today = st.date_input("Дата расчёта", value=date.fromisoformat(saved.get("today", "2026-09-23")))
    growth = {}
    with st.expander("Дополнительный прирост по категориям"):
        st.caption("Контракты и промо сверх выявленного тренда. 0% не отменяет рост из истории.")
        defaults = data.get("growth", pd.DataFrame()) if data else pd.DataFrame()
        for item in categories:
            base = float(defaults.loc[defaults.category == item, "growth_pct"].iloc[0]) if not defaults.empty and (defaults.category == item).any() else 0.0
            growth[item] = st.number_input(f"{item}, %", min_value=-100.0, max_value=1000.0,
                                          value=float(saved.get("growth_override", {}).get(item, base)), step=5.0, key=f"growth_{item}")
    params = dict(today=today.isoformat(), warehouse=warehouse, category=category,
                  service_level=service, review_days=None, growth_override=growth)
    run = st.button("Рассчитать", type="primary", width="stretch", disabled=data is None)
    st.caption("Решение принимает менеджер. Заказы поставщикам автоматически не отправляются.")

current_signature = signature(files, params)
if run and data is not None:
    try:
        with st.spinner("Рассчитываем потребность по поставщикам…"):
            result = calculate(data, params)
        st.session_state.update(result=result, calculation_data=data, calculation_params=params,
                                calculation_signature=current_signature, approvals={}, saved_editors={}, editor_inputs={},
                                generation=st.session_state.get("generation", 0) + 1)
    except Exception as exc:
        # Never allow approval of the old result after a failed new calculation.
        st.session_state.pop("calculation_signature", None)
        show_error(exc)

if "result" not in st.session_state:
    st.info("Выберите данные и нажмите «Рассчитать». Здесь появятся рекомендации, сгруппированные по поставщикам.")
    st.stop()

result = st.session_state.result
dirty = current_signature != st.session_state.get("calculation_signature")
if dirty:
    st.warning("Данные или параметры изменились. Повторите расчёт перед утверждением и экспортом.")
if result.empty:
    st.info("Для выбранного склада и категории нет позиций. Измените фильтры и повторите расчёт.")
    st.stop()

positive = result[result.recommended_qty > 0]
kpis = st.columns(5)
kpis[0].metric("Позиций к заказу", len(positive))
kpis[1].metric("Критичных", int((positive.urgency == "critical").sum()))
# Purchase prices are not part of the contract; do not invent an order amount from sales prices.
price = next((col for col in ("purchase_price", "unit_cost") if col in result), None)
amount = (positive.recommended_qty * pd.to_numeric(positive[price], errors="coerce")).sum(min_count=len(positive)) if price and not positive.empty else None
kpis[2].metric("Сумма заказа, ₸", f"{amount:,.0f}" if amount is not None and pd.notna(amount) else "Нет закупочных цен")
kpis[3].metric("Поставщиков", positive.supplier_id.nunique())
kpis[4].metric("Просроченных позиций", int(result.get("transit_overdue", pd.Series(False, index=result.index)).fillna(False).sum()))
st.caption("Показатели рассчитаны по рекомендациям до ручных правок. Денежная оценка доступна только при наличии закупочных цен.")
author = st.text_input("Кто утверждает заказ", value=st.session_state.get("saved_author", ""), placeholder="Имя и фамилия", key="approver")
st.session_state.saved_author = author
show_all = st.checkbox("Показать все позиции, включая те, где заказ не требуется")
if show_all:
    st.dataframe(result, hide_index=True, width="stretch")
    with st.expander("Карточка любой позиции"):
        position_card(result, st.session_state.calculation_data, "all")

approved_frames = []
for supplier, group in positive.groupby("supplier_id", sort=False):
    group = group.assign(_priority=group.urgency.map({"critical": 0, "high": 1, "normal": 2}).fillna(3)).sort_values(["_priority", "sku", "warehouse"]).drop(columns="_priority").reset_index(drop=True)
    name = str(group.iloc[0].supplier_name)
    key = hashlib.sha256(str(supplier).encode()).hexdigest()[:12] + f"_{st.session_state.generation}"
    with st.expander(f"{name} · {len(group)} позиций · {group.recommended_qty.sum():,.0f} шт.", expanded=True):
        shown = group[["sku", "name", "warehouse", "on_hand", "in_transit", "forecast_horizon", "recommended_qty", "urgency", "confidence"]].copy()
        shown["urgency"] = shown.urgency.map(URGENCY).fillna(shown.urgency)
        shown["confidence"] = shown.confidence.map(CONFIDENCE).fillna(shown.confidence)
        editor_key = f"editor_{key}"
        saved_editors = st.session_state.setdefault("saved_editors", {})
        editor_inputs = st.session_state.setdefault("editor_inputs", {})
        # Keep the input stable during edits. On return from another page, use
        # the saved table as a fresh widget's baseline, without writing widget state.
        if str(supplier) not in editor_inputs:
            editor_inputs[str(supplier)] = saved_editors.get(str(supplier), shown).copy()
        edited = st.data_editor(editor_inputs[str(supplier)], key=editor_key, hide_index=True, width="stretch",
                                disabled=[col for col in shown if col != "recommended_qty"],
                                column_config={
                                    "sku": "Артикул", "name": "Номенклатура", "warehouse": "Склад",
                                    "on_hand": "Остаток", "in_transit": "В пути", "forecast_horizon": "Прогноз",
                                    "recommended_qty": st.column_config.NumberColumn("К заказу ✎", min_value=0, max_value=1_000_000_000, step=1, required=True),
                                    "urgency": "Срочность", "confidence": "Уверенность",
                                })
        saved_editors[str(supplier)] = edited.copy()
        try:
            draft = edited_order(group, edited)
        except ValueError as exc:
            st.session_state.approvals.pop(str(supplier), None)
            st.warning(str(exc))
            continue
        changed = draft[draft.manually_changed]
        for _, row in changed.iterrows():
            st.caption(f"Изменено вручную: {row.sku} / {row.warehouse}: {row.original_qty:g} → {row.recommended_qty:g} шт.")
        st.caption(f"Текущий заказ: {(draft.recommended_qty > 0).sum()} позиций, {draft.recommended_qty.sum():,.0f} шт. Нулевые количества не попадут в выгрузку.")
        with st.expander("Обоснование и история спроса"):
            position_card(group, st.session_state.calculation_data, key)
        approved = st.session_state.approvals.get(str(supplier))
        if approved and approved["fingerprint"] != fingerprint(draft):
            st.session_state.approvals.pop(str(supplier))
            approved = None
            st.info("Количество изменилось после утверждения. Утвердите обновлённый заказ.")
        if st.button(f"Утвердить заказ · {name}", key=f"approve_{key}", type="primary",
                     disabled=dirty or approved is not None or not (draft.recommended_qty > 0).any()):
            try:
                approved = approve(draft, author, st.session_state.calculation_params)
                st.session_state.approvals[str(supplier)] = approved
            except Exception as exc:
                show_error(exc)
        if approved and not dirty:
            st.success(f"Утверждён: {approved['author']} · {approved['approved_at'][:19]} UTC. Сохранён в журнале заказов.")
            snapshot = pd.DataFrame(approved["items"])
            approved_frames.append(snapshot)
            downloads(snapshot, key)
        else:
            st.caption("Экспорт станет доступен после утверждения текущей версии заказа.")

if positive.empty:
    st.success("Пополнение не требуется. Посмотрите все позиции, чтобы проверить остатки и поставки в пути.")
if approved_frames and not dirty:
    st.subheader("Экспорт утверждённых заказов")
    st.caption(f"Выгружаются только утверждённые заказы: {len(approved_frames)} из {positive.supplier_id.nunique()} поставщиков. XLSX — отдельный лист на поставщика; CSV — UTF-8 BOM, разделитель «;».")
    downloads(pd.concat(approved_frames, ignore_index=True), "all_approved")
