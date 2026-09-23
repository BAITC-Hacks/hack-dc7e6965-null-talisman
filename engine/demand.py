"""Разовые крупные заказы (must-have 4) и очистка ряда от дней без товара
(must-have 3). Алгоритм и пороги — docs/PLAN.md, раздел 4, шаги 2-3.
"""
from __future__ import annotations

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
    events = []

    for (sku, warehouse), idx in lines.groupby(["sku", "warehouse"]).groups.items():
        grp = lines.loc[idx]
        pos = grp[(grp["qty"] > 0) & (grp["client_id"] != "BOM")]
        if len(pos) < 3:
            continue
        median = pos["qty"].median()
        mad = (pos["qty"] - median).abs().median()
        scale = 1.4826 * mad if mad > 0 else (pos["qty"] - median).abs().mean()
        if not scale or scale <= 0:
            scale = 1.0

        month = grp["date"].dt.to_period("M")
        median_month_total = grp.assign(month=month).groupby("month")["qty"].sum().median()
        client_months = pos.assign(month=pos["date"].dt.to_period("M")).groupby("client_id")["month"].nunique()

        for i in pos.index:
            qty = lines.at[i, "qty"]
            robust_z = (qty - median) / scale
            significant = qty > ONEOFF_SIGNIFICANCE_FRAC * max(median_month_total, 0)
            irregular = client_months.get(lines.at[i, "client_id"], 0) <= ONEOFF_MAX_CLIENT_MONTHS
            if robust_z > ONEOFF_ROBUST_Z and significant and irregular:
                excluded = qty - median
                lines.at[i, "qty"] = median
                lines.at[i, "oneoff_excluded"] = excluded
                events.append({
                    "sku": sku, "warehouse": warehouse, "date": grp.at[i, "date"],
                    "client_id": grp.at[i, "client_id"], "excluded_qty": excluded,
                })

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
    for (sku, warehouse), grp in monthly.groupby(["sku", "warehouse"]):
        # реиндексируем только числовой ряд — reindex всего grp пытается залить
        # fill_value и в текстовые колонки sku/warehouse, это им не подходит
        actual = grp.set_index("month")["actual"].reindex(
            _month_range(grp["month"].min(), grp["month"].max()), fill_value=0.0
        )
        grp = pd.DataFrame({"actual": actual})
        grp.index.name = "month"

        avail = pd.Series(1.0, index=grp.index)
        sku_stockouts = so[(so["sku"] == sku) & (so["warehouse"] == warehouse)] if not so.empty else so
        if sku_stockouts is not None and not sku_stockouts.empty:
            for m in grp.index:
                month_start = m.start_time
                month_end = m.end_time
                days_in_month = (month_end - month_start).days + 1
                stockout_days = 0
                for _, row in sku_stockouts.iterrows():
                    overlap_start = max(row["start"], month_start)
                    overlap_end = min(row["end"], month_end)
                    if overlap_end >= overlap_start:
                        stockout_days += (overlap_end - overlap_start).days + 1
                avail.loc[m] = max(0.0, (days_in_month - stockout_days) / days_in_month)

        series_median = grp["actual"].median() or 0.0
        clean = grp["actual"].copy()
        low_avail_mask = avail < STOCKOUT_MIN_AVAILABILITY
        clean.loc[~low_avail_mask & (avail > 0)] = (
            grp.loc[~low_avail_mask & (avail > 0), "actual"] / avail.loc[~low_avail_mask & (avail > 0)]
        )
        # почти пустые месяцы (f < 0.5): делить опасно -> заполняем медианой ряда
        clean.loc[low_avail_mask] = series_median
        cap = max(series_median * CLEAN_CAP_MULT, 1.0)
        clean = clean.clip(upper=cap)

        out = pd.DataFrame({
            "sku": sku, "warehouse": warehouse,
            "month": grp.index, "actual": grp["actual"].values,
            "availability_frac": avail.values, "clean": clean.values,
        })
        out["lost_demand"] = (out["clean"] - out["actual"]).clip(lower=0)
        results.append(out)

    return pd.concat(results, ignore_index=True) if results else pd.DataFrame(
        columns=["sku", "warehouse", "month", "actual", "availability_frac", "clean", "lost_demand"]
    )
