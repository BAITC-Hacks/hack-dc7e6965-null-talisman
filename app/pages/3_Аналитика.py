import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import plotly.express as px
import streamlit as st

from app.theme import apply_theme, theme_toggle

st.set_page_config(page_title="Аналитика · Null Talisman", page_icon="📈", layout="wide")
st.session_state.ui_page = "analytics"
theme_toggle()
apply_theme()
st.caption("NULL TALISMAN / СПРОС")
st.title("Спрос по категориям")
if "calculation_data" not in st.session_state:
    st.info("Сначала выполните расчёт на странице заказов.")
    st.stop()

data = st.session_state.calculation_data
try:
    sales = data["sales"].copy()
    sales["date"] = pd.to_datetime(sales.date)
    warehouses = ["Все склады", *sorted(sales.warehouse.unique())]
    warehouse = st.selectbox("Склад для аналитики", warehouses)
    if warehouse != "Все склады":
        sales = sales[sales.warehouse.eq(warehouse)]
    product_columns = ["sku", "category"] + (["unit"] if "unit" in data["products"] else [])
    sales = sales.merge(data["products"][product_columns].drop_duplicates("sku"), on="sku", how="left")
    unit = "шт"
    if "unit" in sales:
        sales["unit"] = sales.unit.fillna("ед.")
        units = sorted(sales.unit.unique())
        if units:
            unit = st.selectbox("Единица измерения", units)
            sales = sales[sales.unit.eq(unit)]
        st.caption("Разные единицы измерения показаны отдельно: метры и штуки не суммируются.")
    sales["category"] = sales.category.fillna("Без категории")
    sales["month"] = sales.date.dt.to_period("M").dt.to_timestamp()
    monthly = sales.groupby(["month", "category"], as_index=False).qty.sum()
    if monthly.empty:
        st.info("Нет продаж для выбранного склада.")
    else:
        st.plotly_chart(px.line(monthly, x="month", y="qty", color="category",
                                labels={"month": "Месяц", "qty": f"Продано, {unit}", "category": "Категория"}), width="stretch")
    st.caption("Фактические продажи после загрузки, включая возвраты. Это обзор исходных данных; очищенный спрос и прогноз доступны в карточке позиции.")
except (KeyError, ValueError, TypeError):
    st.warning("Для аналитики нужны таблицы sales и products с полями date, sku, qty, warehouse, category.")

st.subheader("Товары с устойчивым ростом")
result = st.session_state.get("result", pd.DataFrame())
if "trend_pct_month" in result:
    growing = result[result.trend_pct_month > 0].sort_values("trend_pct_month", ascending=False).head(10)
    st.dataframe(growing[["sku", "name", "warehouse", "trend_pct_month", "confidence"]], hide_index=True,
                 column_config={"sku": "Артикул", "name": "Номенклатура", "warehouse": "Склад",
                                "trend_pct_month": "Рост, % / мес.", "confidence": "Уверенность"})
    st.caption("Из последнего расчёта с его фильтрами. Плановый прирост менеджера в этот рейтинг не входит.")
else:
    st.info("Ядро ещё не передало показатели тренда.")
