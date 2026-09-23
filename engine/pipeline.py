"""recommend() — главный контракт движка. Склеивает io -> demand -> forecast ->
replenish в один DataFrame рекомендаций. Схема входа/выхода — docs/PLAN.md, раздел 3.
"""
from __future__ import annotations

import math

import pandas as pd

from engine import demand, forecast, io, replenish

MONTH_NAMES_RU = {
    1: "январь", 2: "февраль", 3: "март", 4: "апрель", 5: "май", 6: "июнь",
    7: "июль", 8: "август", 9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь",
}

RECOMMEND_COLUMNS = [
    "supplier_id", "supplier_name", "sku", "name", "category", "warehouse",
    "on_hand", "in_transit", "transit_overdue",
    "avg_month_raw", "avg_month_clean", "oneoff_excluded", "lost_demand_added",
    "season_factor", "trend_pct_month", "growth_pct",
    "horizon_days", "forecast_horizon", "safety_stock", "need_raw",
    "recommended_qty", "days_of_cover", "stockout_date", "urgency",
    "confidence", "flags", "explanation",
]

DEFAULT_PARAMS = dict(
    today=None, warehouse=None, category=None, service_level=0.95,
    review_days=None, growth_override=None,
)


def _empty_result() -> pd.DataFrame:
    return pd.DataFrame(columns=RECOMMEND_COLUMNS)


def _build_context(data: dict[str, pd.DataFrame], today: pd.Timestamp) -> dict:
    sales = data["sales"]
    if not sales.empty:
        # io.load_data() больше не знает дату расчёта на этапе загрузки, поэтому
        # будущие относительно `today` продажи отбрасываем здесь же (и для тех
        # вызывающих, кто передал уже загруженный датасет напрямую).
        sales = sales.loc[sales["date"] <= today].copy()
    # BOM разворачиваем на каждый вызов, а не один раз при загрузке: так правки
    # bom.csv/sales.csv (в т.ч. сценарии проверки на странице "Проверки") сразу
    # отражаются в результате.
    sales = io.explode_bom(sales, data.get("bom", pd.DataFrame()))
    trimmed_lines, oneoff_events = demand.detect_and_trim_oneoffs(sales)
    monthly = demand.monthly_clean_series(trimmed_lines, data["stockouts"], today)
    category_seasonal = forecast.build_category_seasonal(monthly, data["products"])
    raw_monthly = (
        demand.build_lines(sales).assign(month=lambda d: d["date"].dt.to_period("M"))
        .groupby(["sku", "warehouse", "month"], as_index=False)["qty"].sum()
        if not sales.empty else pd.DataFrame(columns=["sku", "warehouse", "month", "qty"])
    )
    return {
        "trimmed_lines": trimmed_lines,
        "oneoff_events": oneoff_events,
        "monthly": monthly,
        "raw_monthly": raw_monthly,
        "category_seasonal": category_seasonal,
    }


def _growth_map(data: dict[str, pd.DataFrame], override: dict | None) -> dict[str, float]:
    gmap = {}
    growth = data.get("growth")
    if growth is not None and not growth.empty:
        gmap = dict(zip(growth["category"], growth["growth_pct"]))
    if override:
        gmap.update(override)
    return gmap


def recommend(data: dict[str, pd.DataFrame], params: dict | None = None) -> pd.DataFrame:
    p = {**DEFAULT_PARAMS, **(params or {})}
    if p["today"] is None:
        raise ValueError("params['today'] обязателен")
    today = pd.Timestamp(p["today"])

    # Защита от аномалий во входе: caller (в т.ч. сценарии проверки на странице
    # "Проверки") может подмешать в_transit с сырыми типами (строковая дата и
    # т.п.) без повторного прогона через io.clean() — приводим типы здесь же.
    in_transit = data["in_transit"].copy()
    if not in_transit.empty:
        in_transit["eta"] = pd.to_datetime(in_transit["eta"], errors="coerce")
        in_transit["qty"] = pd.to_numeric(in_transit["qty"], errors="coerce").fillna(0)
        in_transit = in_transit.dropna(subset=["eta"])

    products = data["products"]
    if products.empty:
        return _empty_result()
    if p["category"]:
        products = products[products["category"] == p["category"]]
    if products.empty:
        return _empty_result()

    stock = data["stock"]
    stock = stock[stock["sku"].isin(products["sku"])]
    if p["warehouse"]:
        stock = stock[stock["warehouse"] == p["warehouse"]]
    if stock.empty:
        return _empty_result()

    ctx = _build_context(data, today)
    growth_map = _growth_map(data, p["growth_override"])
    suppliers = data["suppliers"].set_index("supplier_id") if not data["suppliers"].empty else pd.DataFrame()
    products_idx = products.set_index("sku")
    default_season = {m: 1.0 for m in range(1, 13)}

    rows = []
    for _, srow in stock.iterrows():
        sku, warehouse, on_hand = srow["sku"], srow["warehouse"], float(srow["on_hand"])
        if sku not in products_idx.index:
            continue
        prod = products_idx.loc[sku]
        category = prod["category"]
        supplier_id = prod["supplier_id"]
        supplier_name = supplier_id
        lead_time = replenish.DEFAULT_LEAD_TIME_DAYS
        order_cycle = replenish.DEFAULT_REVIEW_DAYS
        if not suppliers.empty and supplier_id in suppliers.index:
            srec = suppliers.loc[supplier_id]
            supplier_name = srec["name"]
            lead_time = float(srec["lead_time_days"])
            order_cycle = float(srec["order_cycle_days"])

        series = ctx["monthly"][(ctx["monthly"]["sku"] == sku) & (ctx["monthly"]["warehouse"] == warehouse)]
        category_index = ctx["category_seasonal"].get(category, default_season)
        growth_pct = float(growth_map.get(category, 0.0))
        model = forecast.forecast_sku(series, category_index, growth_pct)

        h_days = replenish.horizon_days(lead_time, p["review_days"], order_cycle)
        fcst_horizon, avg_daily = replenish.forecast_over_horizon(model, today, h_days, growth_pct)
        cutoff = today + pd.Timedelta(days=h_days)
        in_transit_qty, transit_overdue = replenish.in_transit_for(
            in_transit, sku, warehouse, today, cutoff
        )
        safety_stock = replenish.z_score(p["service_level"]) * model["sigma_month"] * math.sqrt(h_days / 30)
        need_raw = fcst_horizon + safety_stock - on_hand - in_transit_qty

        pack_size = float(prod["pack_size"]) or 1.0
        moq = float(prod["moq"]) or 0.0
        if need_raw <= 0:
            recommended_qty = 0
        else:
            packs = math.ceil(need_raw / pack_size)
            recommended_qty = int(max(moq, packs * pack_size))

        days_of_cover = on_hand / avg_daily if avg_daily > 0 else replenish.BIG_COVER_DAYS
        stockout_date = None
        if days_of_cover < 3650:
            stockout_date = (today + pd.Timedelta(days=days_of_cover)).strftime("%d.%m.%Y")

        if recommended_qty == 0:
            urgency = "normal"
        elif days_of_cover < lead_time:
            urgency = "critical"
        elif avg_daily > 0 and (on_hand + in_transit_qty) / avg_daily < h_days:
            urgency = "high"
        else:
            urgency = "normal"

        oneoff = ctx["oneoff_events"]
        sku_oneoff = oneoff[(oneoff["sku"] == sku) & (oneoff["warehouse"] == warehouse)] if not oneoff.empty else oneoff
        oneoff_excluded = float(sku_oneoff["excluded_qty"].sum()) if sku_oneoff is not None and not sku_oneoff.empty else 0.0
        oneoff_client = None
        if sku_oneoff is not None and not sku_oneoff.empty:
            biggest = sku_oneoff.loc[sku_oneoff["excluded_qty"].idxmax()]
            oneoff_client = biggest["client_id"]

        lost_demand_added = float(series["lost_demand"].sum()) if not series.empty else 0.0
        so = data["stockouts"]
        sku_so = so[(so["sku"] == sku) & (so["warehouse"] == warehouse)] if not so.empty else so
        stockout_days = float(((sku_so["end"] - sku_so["start"]).dt.days + 1).sum()) if sku_so is not None and not sku_so.empty else 0.0

        raw = ctx["raw_monthly"]
        sku_raw = raw[(raw["sku"] == sku) & (raw["warehouse"] == warehouse)] if not raw.empty else raw
        avg_month_raw = float(sku_raw.sort_values("month")["qty"].tail(6).mean()) if sku_raw is not None and not sku_raw.empty else 0.0
        avg_month_clean = float(series.sort_values("month")["clean"].tail(6).mean()) if not series.empty else model["level"]

        next_month = (today + pd.DateOffset(months=1)).month
        season_factor = model["season_index"].get(next_month, 1.0)

        transit_rows = in_transit[(in_transit["sku"] == sku) & (in_transit["warehouse"] == warehouse)] if not in_transit.empty else in_transit
        transit_eta = None
        if transit_rows is not None and not transit_rows.empty:
            transit_eta = transit_rows.sort_values("eta")["eta"].iloc[0].strftime("%d.%m.%Y")

        flags = list(model.get("flags", []))
        if transit_overdue:
            flags.append("transit_overdue")

        explanation = replenish.build_explanation(
            horizon=h_days, lead_time=int(lead_time), review=int(order_cycle),
            forecast_horizon=fcst_horizon, season_factor=season_factor,
            season_month_label=MONTH_NAMES_RU.get(next_month, ""), trend_pct=model["trend_pct_month"],
            oneoff_excluded=oneoff_excluded, oneoff_client=oneoff_client,
            lost_demand=lost_demand_added, stockout_days=stockout_days,
            safety_stock=safety_stock, service_level=p["service_level"],
            on_hand=on_hand, in_transit=in_transit_qty, transit_eta=transit_eta,
            transit_overdue=transit_overdue, need_raw=need_raw, recommended_qty=recommended_qty,
            pack_size=pack_size, urgency=urgency, stockout_date=stockout_date,
            lead_time_arrival=(today + pd.Timedelta(days=lead_time)).strftime("%d.%m.%Y"),
        )

        rows.append({
            "supplier_id": supplier_id, "supplier_name": supplier_name,
            "sku": sku, "name": prod["name"], "category": category, "warehouse": warehouse,
            "on_hand": on_hand, "in_transit": in_transit_qty, "transit_overdue": transit_overdue,
            "avg_month_raw": avg_month_raw, "avg_month_clean": avg_month_clean,
            "oneoff_excluded": oneoff_excluded, "lost_demand_added": lost_demand_added,
            "season_factor": season_factor, "trend_pct_month": model["trend_pct_month"],
            "growth_pct": growth_pct, "horizon_days": h_days, "forecast_horizon": fcst_horizon,
            "safety_stock": safety_stock, "need_raw": need_raw, "recommended_qty": recommended_qty,
            "days_of_cover": days_of_cover, "stockout_date": stockout_date, "urgency": urgency,
            "confidence": model["confidence"], "flags": ",".join(flags), "explanation": explanation,
        })

    if not rows:
        return _empty_result()
    return pd.DataFrame(rows, columns=RECOMMEND_COLUMNS)


def sku_series(data: dict[str, pd.DataFrame], sku: str, warehouse: str,
               today: pd.Timestamp | None = None, growth_pct: float = 0.0,
               forward_months: int = 6) -> pd.DataFrame:
    """История + прогноз для графика одной позиции.
    Колонки: month, raw, clean, forecast, oneoff (исключено шт. за месяц),
    stockout_days (дней без товара за месяц). today=None -> берём последнюю
    дату продаж в данных (карточка в UI вызывается без даты расчёта)."""
    if today is None:
        sales_dates = pd.to_datetime(data.get("sales", pd.DataFrame()).get("date"), errors="coerce")
        latest_date = sales_dates.max() if sales_dates is not None else pd.NaT
        today = latest_date if pd.notna(latest_date) else pd.Timestamp.today().normalize()
    today = pd.Timestamp(today)
    ctx = _build_context(data, today)
    products = data["products"]
    category = None
    prod_match = products[products["sku"] == sku]
    if not prod_match.empty:
        category = prod_match.iloc[0]["category"]
    category_index = ctx["category_seasonal"].get(category, {m: 1.0 for m in range(1, 13)})

    series = ctx["monthly"][(ctx["monthly"]["sku"] == sku) & (ctx["monthly"]["warehouse"] == warehouse)].sort_values("month")
    raw = ctx["raw_monthly"]
    raw = raw[(raw["sku"] == sku) & (raw["warehouse"] == warehouse)] if not raw.empty else raw

    model = forecast.forecast_sku(series, category_index, growth_pct)

    oneoff_events = ctx["oneoff_events"]
    if not oneoff_events.empty:
        oneoff_events = oneoff_events[
            (oneoff_events["sku"] == sku) & (oneoff_events["warehouse"] == warehouse)
        ].copy()
        oneoff_events["month"] = oneoff_events["date"].dt.to_period("M")
        oneoff_by_month = oneoff_events.groupby("month")["excluded_qty"].sum()
    else:
        oneoff_by_month = pd.Series(dtype=float)

    out_rows = []
    for _, r in series.iterrows():
        month = r["month"]
        raw_val = raw[raw["month"] == month]["qty"].sum() if raw is not None and not raw.empty else r["actual"]
        out_rows.append({
            "month": str(month), "raw": float(raw_val), "clean": float(r["clean"]),
            "forecast": None, "oneoff": float(oneoff_by_month.get(month, 0.0)),
            "stockout_days": int(round((1.0 - float(r["availability_frac"])) * month.days_in_month)),
        })

    # Match replenish.forecast_over_horizon: the calculation month has h=0.
    # Anchor to the selected date, even when the last sale was months ago.
    for h in range(forward_months):
        m = today.to_period("M") + h
        val = forecast.forecast_month_value(model, h, m.month, growth_pct)
        out_rows.append({
            "month": str(m), "raw": None, "clean": None, "forecast": float(val),
            "oneoff": 0.0, "stockout_days": 0,
        })

    return pd.DataFrame(
        out_rows,
        columns=["month", "raw", "clean", "forecast", "oneoff", "stockout_days"],
    )
