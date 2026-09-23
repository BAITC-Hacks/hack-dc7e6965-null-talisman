import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from app.checks import SCENARIOS, run_checks

st.set_page_config(page_title="Проверки · Null Talisman", page_icon="🧪", layout="wide")
st.session_state.ui_page = "checks"
st.caption("NULL TALISMAN / ПРОВЕРКА РЕШЕНИЯ")
st.title("Пять требований — пять живых проверок")
st.write("Сравниваем результат ядра до и после изменения входных данных. Проверки используют копии таблиц и не меняют ваши заказы.")
st.caption("Проверяется весь набор данных последнего расчёта, независимо от фильтров склада и категории. Для эталонных сценариев нужны DEMO-SEASON, DEMO-STOCKOUT и DEMO-ONEOFF.")
st.caption("Для упущенного спроса проверяем рост и прогноза, и потребности до округления — по строгому критерию трека.")

if "calculation_data" not in st.session_state or not st.session_state.get("calculation_signature"):
    st.info("Сначала выполните успешный расчёт на странице «Заказы поставщикам».")
    st.caption("Откройте главную страницу в меню слева.")
    st.stop()

signature = st.session_state.calculation_signature
cache = st.session_state.setdefault("check_cache", {})
run = st.button("Прогнать все", type="primary")
refresh = st.button("Повторить без кэша", disabled=signature not in cache)
if run and signature in cache and not refresh:
    st.session_state.check_report = cache[signature]
    st.info("Показан сохранённый прогон для тех же данных и параметров.")
elif run or refresh:
    progress = st.progress(0.0, text=SCENARIOS[0][0])
    def update_progress(fraction):
        completed = round(fraction * len(SCENARIOS))
        text = SCENARIOS[completed][0] if completed < len(SCENARIOS) else "Проверки завершены"
        progress.progress(fraction, text=text)
    try:
        checks = run_checks(st.session_state.calculation_data, st.session_state.calculation_params,
                            update_progress)
        report = (signature, checks, datetime.now(timezone.utc).isoformat())
        st.session_state.check_report = report
        cache[signature] = report
        while len(cache) > 4:
            del cache[next(iter(cache))]
    except Exception:
        st.warning("Расчётный модуль пока недоступен. Подключите ядро и повторите проверку.")
    progress.empty()

report = st.session_state.get("check_report")
if not report or report[0] != signature:
    st.info("Нажмите «Прогнать все», чтобы получить результаты для текущего расчёта.")
    st.stop()

checks = report[1]
if len(report) > 2:
    st.caption(f"Прогон: {report[2][:19]} UTC · суммарно {sum(check.elapsed_seconds for check in checks):.1f} с. Изменение данных или параметров требует нового прогона.")
passed = sum(check.status == "passed" for check in checks)
st.metric("Подтверждено требований", f"{passed} / 5")
for check in checks:
    icon = {"passed": "✅", "failed": "❌", "unavailable": "⚪", "error": "⚠️"}[check.status]
    with st.container(border=True):
        st.subheader(f"{icon} {check.title}")
        st.write(check.message)
        st.caption(f"Время сценария: {check.elapsed_seconds:.1f} с")
        if check.rows:
            st.dataframe(pd.DataFrame(check.rows), hide_index=True, width="stretch")
            chart = pd.DataFrame(check.rows).set_index("Сценарий")[["До", "После"]]
            st.bar_chart(chart, horizontal=True)
st.caption("Белый индикатор означает недостаток данных, а не прохождение. Красный — проверенное несоответствие. Эта страница не заменяет pytest команды.")
