"""Потребность, рекомендованное количество, срочность, обоснование.
Алгоритм — docs/PLAN.md, раздел 4, шаг 5.
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd

from engine.forecast import forecast_month_value

DEFAULT_LEAD_TIME_DAYS = 14
DEFAULT_REVIEW_DAYS = 14
BIG_COVER_DAYS = 9999.0


def z_score(service_level: float) -> float:
    service_level = min(max(service_level, 0.50), 0.999)
    return NormalDist().inv_cdf(service_level)


def horizon_days(lead_time_days: float, review_days: float | None, order_cycle_days: float) -> int:
    review = review_days if review_days is not None else order_cycle_days
    return max(1, int(round((lead_time_days or DEFAULT_LEAD_TIME_DAYS) + (review or DEFAULT_REVIEW_DAYS))))


def forecast_over_horizon(model: dict, today: pd.Timestamp, days: int, growth_pct: float) -> tuple[float, float]:
    """Сумма прогноза по дням горизонта + средний дневной прогноз. Модель месячная,
    поэтому идём по дням и берём дневную ставку месяца, в который попадает день."""
    total = 0.0
    today_period = today.to_period("M")
    month_cache: dict[int, float] = {}
    d = today + pd.Timedelta(days=1)
    end = today + pd.Timedelta(days=days)
    while d <= end:
        month_period = d.to_period("M")
        months_ahead = (month_period.year - today_period.year) * 12 + (month_period.month - today_period.month)
        if months_ahead not in month_cache:
            month_val = forecast_month_value(model, months_ahead, d.month, growth_pct)
            month_cache[months_ahead] = month_val / d.days_in_month
        total += month_cache[months_ahead]
        d += pd.Timedelta(days=1)
    avg_daily = total / days if days > 0 else 0.0
    return total, avg_daily


def in_transit_for(in_transit: pd.DataFrame, sku: str, warehouse: str, today: pd.Timestamp,
                    cutoff: pd.Timestamp) -> tuple[float, bool]:
    if in_transit.empty:
        return 0.0, False
    rows = in_transit[(in_transit["sku"] == sku) & (in_transit["warehouse"] == warehouse)]
    if rows.empty:
        return 0.0, False
    overdue = bool((rows["eta"] < today).any())
    included = rows[rows["eta"] <= cutoff]["qty"].sum()
    return float(included), overdue


def build_explanation(*, horizon: int, lead_time: int, review: int, forecast_horizon: float,
                       season_factor: float, season_month_label: str, trend_pct: float,
                       oneoff_excluded: float, oneoff_client: str | None,
                       lost_demand: float, stockout_days: float, safety_stock: float,
                       service_level: float, on_hand: float, in_transit: float,
                       transit_eta: str | None, transit_overdue: bool,
                       need_raw: float, recommended_qty: int, pack_size: float,
                       urgency: str, stockout_date: str | None, lead_time_arrival: str | None) -> str:
    parts = [
        f"Прогноз на {horizon} дн. (срок поставки {lead_time} + цикл {review}): {forecast_horizon:.0f} шт."
    ]
    season_bits = []
    if abs(season_factor - 1.0) > 0.05:
        season_bits.append(f"сезон ×{season_factor:.2f} ({season_month_label})")
    if abs(trend_pct) >= 1.0:
        sign = "+" if trend_pct >= 0 else ""
        season_bits.append(f"рост {sign}{trend_pct:.0f}%/мес")
    if season_bits:
        parts.append(", ".join(season_bits).capitalize() + ".")
    if oneoff_excluded > 0:
        client_bit = f", клиент {oneoff_client}" if oneoff_client else ""
        parts.append(f"Исключён разовый заказ {oneoff_excluded:.0f} шт{client_bit}.")
    if lost_demand > 0:
        parts.append(f"Добавлено {lost_demand:.0f} шт упущенного спроса ({stockout_days:.0f} дн. без товара).")
    parts.append(f"Страховой запас {safety_stock:.0f} шт ({int(service_level * 100)}%).")
    transit_bit = f"Остаток {on_hand:.0f}"
    if in_transit > 0 or transit_overdue:
        transit_bit += f", в пути {in_transit:.0f}"
        if transit_eta:
            transit_bit += f" (ETA {transit_eta}"
            transit_bit += ", просрочено)" if transit_overdue else ")"
    parts.append(transit_bit + ".")
    if recommended_qty > 0:
        rounded_bit = f" → округлено до {recommended_qty} (упаковка {pack_size:.0f})" if recommended_qty != round(need_raw) else ""
        parts.append(f"Заказать {max(need_raw, 0):.0f}{rounded_bit}.")
    else:
        parts.append("Заказ не требуется.")
    if urgency == "critical" and stockout_date:
        arrival_bit = f", поставка придёт не раньше {lead_time_arrival}" if lead_time_arrival else ""
        parts.append(f"Критично: закончится {stockout_date}{arrival_bit}.")
    elif urgency == "high":
        parts.append("Высокая срочность.")
    return " ".join(parts)
