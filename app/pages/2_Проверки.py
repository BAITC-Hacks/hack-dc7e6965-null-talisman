import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from app.checks import run_checks

st.set_page_config(page_title="Проверки · Null Talisman", page_icon="🧪", layout="wide")
st.session_state.ui_page = "checks"
st.caption("NULL TALISMAN / ПРОВЕРКА РЕШЕНИЯ")
st.title("Пять требований — пять живых проверок")
st.write("Сравниваем результат ядра до и после изменения входных данных. Проверки используют копии таблиц и не меняют ваши заказы.")
st.caption("Проверяется весь набор данных последнего расчёта, независимо от фильтров склада и категории. Для эталонных сценариев нужны DEMO-SEASON, DEMO-STOCKOUT и DEMO-ONEOFF.")
st.caption("Упущенный спрос проверяем по росту прогноза, как в приёмочных тестах команды. Итоговый заказ дополнительно зависит от страхового запаса, остатков и поставок в пути.")

if "calculation_data" not in st.session_state or not st.session_state.get("calculation_signature"):
    st.info("Сначала выполните успешный расчёт на странице «Заказы поставщикам».")
    st.caption("Откройте главную страницу в меню слева.")
    st.stop()

signature = st.session_state.calculation_signature
if st.button("Прогнать все", type="primary"):
    progress = st.progress(0.0, text="Выполняем контрольные сценарии…")
    try:
        checks = run_checks(st.session_state.calculation_data, st.session_state.calculation_params,
                            lambda fraction: progress.progress(fraction, text="Выполняем контрольные сценарии…"))
        st.session_state.check_report = (signature, checks)
    except Exception:
        st.warning("Расчётный модуль пока недоступен. Подключите ядро и повторите проверку.")
    progress.empty()

report = st.session_state.get("check_report")
if not report or report[0] != signature:
    st.info("Нажмите «Прогнать все», чтобы получить результаты для текущего расчёта.")
    st.stop()

checks = report[1]
passed = sum(check.status == "passed" for check in checks)
st.metric("Подтверждено требований", f"{passed} / 5")
for check in checks:
    icon = {"passed": "✅", "failed": "❌", "unavailable": "⚪", "error": "⚠️"}[check.status]
    with st.container(border=True):
        st.subheader(f"{icon} {check.title}")
        st.write(check.message)
        if check.rows:
            st.dataframe(pd.DataFrame(check.rows), hide_index=True, width="stretch")
            chart = pd.DataFrame(check.rows).set_index("Сценарий")[["До", "После"]]
            st.bar_chart(chart, horizontal=True)
st.caption("Белый индикатор означает недостаток данных, а не прохождение. Красный — проверенное несоответствие. Эта страница не заменяет pytest команды.")
