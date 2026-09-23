"""Разовые крупные заказы (must-have 4) и очистка ряда от дней без товара
(must-have 3). Алгоритм и пороги — docs/PLAN.md, раздел 4, шаги 2-3.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ONEOFF_ROBUST_Z = 6.0
ONEOFF_SIGNIFICANCE_FRAC = 0.3
ONEOFF_MAX_CLIENT_MONTHS = 2

STOCKOUT_MIN_AVAILABILITY = 0.5
CLEAN_CAP_MULT = 3.0


def build_lines(sales: pd.DataFrame) -> pd.DataFrame:
    """Строка заказа = сумма qty по (sku, warehouse, date, client_id)."""
    if sales.empty:
        return pd.DataFrame(columns=["sku", "warehouse", "date", "client_id", "qty"])
    return (
        sales.groupby(["sku", "warehouse", "date", "client_id"], as_index=False)["qty"]
        .sum()
    )


def detect_and_trim_oneoffs(sales: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Находит разовые крупные строки заказа и обрезает их до медианы по sku/warehouse.

    Возвращает (trimmed_lines, oneoff_events):
    - trimmed_lines: те же строки, но qty разовых заказов обрезано до медианы,
      плюс колонка oneoff_excluded (сколько штук исключено из этой строки).
    - oneoff_events: по одной строке на каждый найденный разовый заказ, для
      обоснования и графика (sku, warehouse, date, client_id, excluded_qty).
    """
    lines = build_lines(sales)
    if lines.empty:
        return lines.assign(oneoff_excluded=pd.Series(dtype=float)), pd.DataFrame(
            columns=["sku", "warehouse", "date", "client_id", "excluded_qty"]
        )

    lines = lines.copy()
    lines["qty"] = lines["qty"].astype(float)  # медиана/обрезка разовых заказов даёт float
    lines["oneoff_excluded"] = 0.0
    # .dt.to_period один раз на весь датасет, а не в цикле на каждую группу —
    # раньше это (и построчный python-цикл ниже) держало ~150к строк продаж на
    # каждый вызов recommend(), что превращало страницу "Проверки" в минуты ожидания.
    lines["month"] = lines["date"].dt.to_period("M")
    events = []

    for (sku, warehouse), grp in lines.groupby(["sku", "warehouse"], sort=False):
        pos = grp[(grp["qty"] > 0) & (grp["client_id"] != "BOM")]
        if len(pos) < 3:
            continue
        median = pos["qty"].median()
        mad = (pos["qty"] - median).abs().median()
        scale = 1.4826 * mad if mad > 0 else (pos["qty"] - median).abs().mean()
        if not scale or scale <= 0:
            scale = 1.0

        median_month_total = grp.groupby("month")["qty"].sum().median()
        client_months = pos.groupby("client_id")["month"].nunique()

        robust_z = (pos["qty"] - median) / scale
        significant = pos["qty"] > ONEOFF_SIGNIFICANCE_FRAC * max(median_month_total, 0)
        irregular = pos["client_id"].map(client_months).fillna(0) <= ONEOFF_MAX_CLIENT_MONTHS
        flagged = pos[(robust_z > ONEOFF_ROBUST_Z) & significant & irregular]
        if flagged.empty:
            continue

        excluded = flagged["qty"] - median
        lines.loc[flagged.index, "qty"] = median
        lines.loc[flagged.index, "oneoff_excluded"] = excluded
        for i in flagged.index:
            events.append({
                "sku": sku, "warehouse": warehouse, "date": flagged.at[i, "date"],
                "client_id": flagged.at[i, "client_id"], "excluded_qty": excluded.at[i],
            })

    lines = lines.drop(columns=["month"])
    return lines, pd.DataFrame(events, columns=["sku", "warehouse", "date", "client_id", "excluded_qty"])


def _month_range(start: pd.Period, end: pd.Period) -> pd.PeriodIndex:
    return pd.period_range(start, end, freq="M")


def monthly_clean_series(trimmed_lines: pd.DataFrame, stockouts: pd.DataFrame,
                          today: pd.Timestamp) -> pd.DataFrame:
    """Помесячный ряд по (sku, warehouse) после обрезки разовых заказов и
    компенсации дней без товара. Текущий неполный месяц исключается из ряда —
    # ponytail: 2-3 дня месяца дают слишком шумную оценку, при необходимости
    # заменить на масштабирование по прошедшим дням.
    """
    if trimmed_lines.empty:
        return pd.DataFrame(columns=[
            "sku", "warehouse", "month", "actual", "availability_frac", "clean", "lost_demand",
        ])

    current_month = today.to_period("M")
    df = trimmed_lines.copy()
    df["month"] = df["date"].dt.to_period("M")
    df = df[df["month"] < current_month]

    monthly = df.groupby(["sku", "warehouse", "month"], as_index=False)["qty"].sum().rename(
        columns={"qty": "actual"}
    )

    so = stockouts.copy()
    if not so.empty:
        so["start_month"] = so["start"].dt.to_period("M")
        so["end_month"] = so["end"].dt.to_period("M")

    results = []
    for (sku, warehouse), grp in monthly.groupby(["sku", "warehouse"], sort=False):
        # реиндексируем только числовой ряд, не весь grp — заливка fill_value
        # в текстовые колонки sku/warehouse не нужна и не подходит по типу
        month_index = _month_range(grp["month"].min(), grp["month"].max())
        actual = grp.set_index("month")["actual"].reindex(month_index, fill_value=0.0)

        avail = np.ones(len(month_index))
        sku_stockouts = so[(so["sku"] == sku) & (so["warehouse"] == warehouse)] if not so.empty else so
        if sku_stockouts is not None and not sku_stockouts.empty:
            # редкий путь (единицы sku из ~сотен имеют stockout) — точный
            # двойной цикл месяц×период здесь не влияет на общее время расчёта
            for i, m in enumerate(month_index):
                days_in_month = m.days_in_month
                stockout_days = 0
                for _, row in sku_stockouts.iterrows():
                    overlap_start = max(row["start"], m.start_time)
                    overlap_end = min(row["end"], m.end_time)
                    if overlap_end >= overlap_start:
                        stockout_days += (overlap_end - overlap_start).days + 1
                avail[i] = max(0.0, (days_in_month - stockout_days) / days_in_month)

        actual_vals = actual.values
        series_median = float(np.median(actual_vals)) if len(actual_vals) else 0.0
        low_avail_mask = avail < STOCKOUT_MIN_AVAILABILITY
        divisor = np.where(avail > 0, avail, 1.0)  # избегаем деления на 0 (результат всё равно отбрасывается маской)
        # почти пустые месяцы (f < 0.5): делить опасно -> заполняем медианой ряда
        clean = np.where(low_avail_mask, series_median, actual_vals / divisor)
        cap = max(series_median * CLEAN_CAP_MULT, 1.0)
        clean = np.minimum(clean, cap)

        out = pd.DataFrame({
            "sku": sku, "warehouse": warehouse,
            "month": month_index, "actual": actual_vals,
            "availability_frac": avail, "clean": clean,
        })
        out["lost_demand"] = np.clip(out["clean"] - out["actual"], 0, None)
        results.append(out)

    return pd.concat(results, ignore_index=True) if results else pd.DataFrame(
        columns=["sku", "warehouse", "month", "actual", "availability_frac", "clean", "lost_demand"]
    )
