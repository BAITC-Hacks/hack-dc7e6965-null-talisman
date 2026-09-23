"""Юнит-тесты engine/demand.py на маленьких синтетических данных — без
обращения к data/generate.py. docs/PLAN-2.md, задача 2 (Абдуали)."""
from __future__ import annotations

import pandas as pd
import pytest

from engine.demand import (
    CLEAN_CAP_MULT,
    STOCKOUT_MIN_AVAILABILITY,
    detect_and_trim_oneoffs,
    monthly_clean_series,
)

TODAY = pd.Timestamp("2026-09-23")
EMPTY_STOCKOUTS = pd.DataFrame(columns=["sku", "warehouse", "start", "end"])


def _sale(date, sku="SKU-1", warehouse="WH1", qty=10, client="C1"):
    return {"date": pd.Timestamp(date), "sku": sku, "warehouse": warehouse,
            "qty": qty, "client_id": client, "price": 100.0}


# ---------------------------------------------------------------- one-off

def test_oneoff_large_order_from_new_client_is_trimmed_to_median():
    """Разовая крупная покупка от клиента, который больше этот sku не берёт,
    обрезается до медианы строки, а излишек попадает в oneoff_events."""
    rows = [_sale(f"2026-0{m}-10", client="REGULAR") for m in range(1, 7)]  # медиана = 10
    rows.append(_sale("2026-07-10", qty=500, client="ONE-TIME"))  # 50x медианы, разово
    sales = pd.DataFrame(rows)

    trimmed, events = detect_and_trim_oneoffs(sales)

    assert len(events) == 1
    assert events.iloc[0]["client_id"] == "ONE-TIME"
    assert events.iloc[0]["excluded_qty"] == pytest.approx(490.0)
    trimmed_row = trimmed[trimmed["client_id"] == "ONE-TIME"].iloc[0]
    assert trimmed_row["qty"] == pytest.approx(10.0)  # обрезано до медианы, не удалено
    assert trimmed_row["oneoff_excluded"] == pytest.approx(490.0)


def test_regular_bulk_client_is_not_trimmed():
    """Крупный, но ПОСТОЯННЫЙ клиент (покупает несколько месяцев подряд) не
    считается разовым заказом, даже если его объём — явный выброс по robust-z."""
    rows = [_sale(f"2026-0{m}-10", client="SMALL", qty=10) for m in range(1, 5)]
    # тот же крупный клиент покупает в трёх разных месяцах -> не "разовый"
    rows += [_sale(f"2026-0{m}-15", client="WHOLESALE", qty=400) for m in range(1, 4)]
    sales = pd.DataFrame(rows)

    trimmed, events = detect_and_trim_oneoffs(sales)

    assert events.empty
    wholesale = trimmed[trimmed["client_id"] == "WHOLESALE"]
    assert (wholesale["qty"] == 400).all()


def test_mild_variance_within_robust_z_threshold_is_not_flagged():
    """Естественный разброс (median±небольшая амплитуда): даже более крупная и
    значимая по объёму строка, но недостаточно выделяющаяся по robust-z
    (< 6 стандартных отклонений), не считается разовым заказом."""
    rows = [_sale(f"2026-0{m}-10", client=f"C{m}", qty=(1 if m % 2 else 2)) for m in range(1, 7)]
    rows.append(_sale("2026-07-10", qty=3, client="C9"))  # выше обычного, но z ~ 2, не 6+
    sales = pd.DataFrame(rows)

    _, events = detect_and_trim_oneoffs(sales)
    assert events.empty


def test_bom_synthetic_rows_are_never_flagged_as_oneoff():
    """Строки, развёрнутые из BOM (client_id='BOM'), не должны обрезаться —
    это агрегированный производный спрос, а не заказ одного клиента."""
    rows = [_sale(f"2026-0{m}-10", client="C1", qty=10) for m in range(1, 7)]
    rows.append(_sale("2026-07-10", qty=500, client="BOM"))
    sales = pd.DataFrame(rows)

    trimmed, events = detect_and_trim_oneoffs(sales)
    assert events.empty
    assert trimmed.loc[trimmed["client_id"] == "BOM", "qty"].iloc[0] == 500


# ------------------------------------------------------------ short/empty

def test_empty_sales_produce_empty_result_without_raising():
    trimmed, events = detect_and_trim_oneoffs(pd.DataFrame(columns=["date", "sku", "warehouse", "qty", "client_id", "price"]))
    assert trimmed.empty and events.empty
    monthly = monthly_clean_series(trimmed, EMPTY_STOCKOUTS, TODAY)
    assert monthly.empty


def test_one_or_two_lines_do_not_trigger_oneoff_detection():
    """detect_and_trim_oneoffs требует минимум 3 положительные строки в группе,
    иначе медиана/MAD не осмысленны — короткая история не должна валить расчёт."""
    sales = pd.DataFrame([_sale("2026-01-10", qty=5), _sale("2026-02-10", qty=5000)])
    trimmed, events = detect_and_trim_oneoffs(sales)
    assert events.empty
    assert trimmed["qty"].tolist() == [5.0, 5000.0]  # ничего не тронуто


# --------------------------------------------------------- stockout compensation

def test_partial_availability_month_is_scaled_up():
    """f=0.6 (>=0.5): продажи месяца делятся на долю доступности, а не заменяются."""
    sales = pd.DataFrame([
        _sale("2026-01-15", client=f"C{i}", qty=10) for i in range(3)
    ] + [_sale("2026-02-05", client="C9", qty=60)])  # февраль: 12 дней без товара из 28
    trimmed, _ = detect_and_trim_oneoffs(sales)
    stockouts = pd.DataFrame([{
        "sku": "SKU-1", "warehouse": "WH1",
        "start": pd.Timestamp("2026-02-01"), "end": pd.Timestamp("2026-02-12"),
    }])
    monthly = monthly_clean_series(trimmed, stockouts, pd.Timestamp("2026-03-01"))
    feb = monthly[monthly["month"] == pd.Period("2026-02", freq="M")].iloc[0]

    days_in_feb = 28
    expected_f = (days_in_feb - 12) / days_in_feb
    assert feb["availability_frac"] == pytest.approx(expected_f)
    assert feb["availability_frac"] >= STOCKOUT_MIN_AVAILABILITY
    assert feb["clean"] == pytest.approx(60 / expected_f)
    assert feb["lost_demand"] > 0


def test_near_full_outage_month_is_replaced_by_series_median():
    """f<0.5: делить на почти нулевую доступность опасно -> берём медиану ряда."""
    sales = pd.DataFrame([
        _sale(f"2026-0{m}-10", client=f"C{m}", qty=100) for m in range(1, 5)
    ] + [_sale("2026-05-03", client="C9", qty=5)])  # май: 26 из 31 дня без товара
    trimmed, _ = detect_and_trim_oneoffs(sales)
    stockouts = pd.DataFrame([{
        "sku": "SKU-1", "warehouse": "WH1",
        "start": pd.Timestamp("2026-05-01"), "end": pd.Timestamp("2026-05-26"),
    }])
    monthly = monthly_clean_series(trimmed, stockouts, pd.Timestamp("2026-06-01"))
    may = monthly[monthly["month"] == pd.Period("2026-05", freq="M")].iloc[0]

    assert may["availability_frac"] < STOCKOUT_MIN_AVAILABILITY
    assert may["clean"] == pytest.approx(100.0)  # медиана остальных месяцев
    assert may["lost_demand"] == pytest.approx(95.0)


def test_restored_demand_is_capped_at_three_times_median():
    """Даже при экстремально низкой доступности восстановленный спрос не может
    превысить CLEAN_CAP_MULT x медиана ряда — защита от деления на почти ноль."""
    sales = pd.DataFrame([
        _sale(f"2026-0{m}-10", client=f"C{m}", qty=10) for m in range(1, 5)
    ] + [_sale("2026-05-01", client="C9", qty=9)])  # май: 1 день доступности из 31
    trimmed, _ = detect_and_trim_oneoffs(sales)
    stockouts = pd.DataFrame([{
        "sku": "SKU-1", "warehouse": "WH1",
        "start": pd.Timestamp("2026-05-02"), "end": pd.Timestamp("2026-05-31"),
    }])
    monthly = monthly_clean_series(trimmed, stockouts, pd.Timestamp("2026-06-01"))
    may = monthly[monthly["month"] == pd.Period("2026-05", freq="M")].iloc[0]

    median = pd.Series([10.0, 10.0, 10.0, 10.0, 9.0]).median()  # ряд включает и май
    assert may["clean"] <= median * CLEAN_CAP_MULT + 1e-9


def test_no_stockout_data_leaves_availability_at_full():
    sales = pd.DataFrame([_sale(f"2026-0{m}-10", client=f"C{m}", qty=10) for m in range(1, 5)])
    trimmed, _ = detect_and_trim_oneoffs(sales)
    monthly = monthly_clean_series(trimmed, EMPTY_STOCKOUTS, pd.Timestamp("2026-05-01"))
    assert (monthly["availability_frac"] == 1.0).all()
    assert (monthly["clean"] == monthly["actual"]).all()
    assert (monthly["lost_demand"] == 0).all()


def test_current_incomplete_month_is_excluded_from_series():
    """Текущий (незавершённый) месяц не участвует в помесячном ряде —
    несколько дней месяца дают слишком шумную оценку."""
    sales = pd.DataFrame([
        _sale("2026-08-10", qty=10), _sale("2026-09-05", qty=999),
    ])
    trimmed, _ = detect_and_trim_oneoffs(sales)
    monthly = monthly_clean_series(trimmed, EMPTY_STOCKOUTS, pd.Timestamp("2026-09-23"))
    assert list(monthly["month"]) == [pd.Period("2026-08", freq="M")]
