from __future__ import annotations

import pandas as pd


EXPECTED_COLUMNS = [
    "supplier_id",
    "supplier_name",
    "sku",
    "name",
    "category",
    "warehouse",
    "on_hand",
    "in_transit",
    "transit_overdue",
    "avg_month_raw",
    "avg_month_clean",
    "oneoff_excluded",
    "lost_demand_added",
    "season_factor",
    "trend_pct_month",
    "growth_pct",
    "horizon_days",
    "forecast_horizon",
    "safety_stock",
    "need_raw",
    "recommended_qty",
    "days_of_cover",
    "stockout_date",
    "urgency",
    "confidence",
    "flags",
    "explanation",
]


def test_recommend_returns_stable_ui_contract() -> None:
    from engine.pipeline import recommend

    result = recommend(data=None, params={"today": "2026-09-23"})

    assert isinstance(result, pd.DataFrame)
    assert result.columns.tolist() == EXPECTED_COLUMNS
    assert not result.empty
    assert result["explanation"].str.strip().ne("").all()
    assert set(result["urgency"]).issubset({"critical", "high", "normal"})


def test_recommend_returns_a_fresh_dataframe() -> None:
    from engine.pipeline import recommend

    first = recommend(data=None, params={"today": "2026-09-23"})
    original = int(first.loc[0, "recommended_qty"])
    first.loc[0, "recommended_qty"] = original + 999

    second = recommend(data=None, params={"today": "2026-09-23"})

    assert int(second.loc[0, "recommended_qty"]) == original
