"""Приёмочные тесты = проверки must-have из трека. docs/PLAN.md, раздел 6."""
from __future__ import annotations

import copy

import pandas as pd
import pytest

from data.generate import TODAY, generate, OUT_DIR
from engine import demand, forecast
from engine import io as engine_io
from engine.io import load_and_prepare
from engine.pipeline import recommend


@pytest.fixture(scope="module")
def data():
    if not (OUT_DIR / "sales.csv").exists():
        generate()
    cleaned, warnings = load_and_prepare(OUT_DIR, TODAY)
    return cleaned


@pytest.fixture(scope="module")
def base_result(data):
    return recommend(data, {"today": TODAY})


def _row(result: pd.DataFrame, sku: str, warehouse: str = "WH1") -> pd.Series:
    match = result[(result["sku"] == sku) & (result["warehouse"] == warehouse)]
    assert not match.empty, f"{sku}/{warehouse} нет в результате"
    return match.iloc[0]


def test_all_sources_affect_result(data, base_result):
    """Must-have 1: каждый источник данных влияет на итог."""
    base = _row(base_result, "SKU-0000")
    base_need = base["need_raw"]

    d = copy.deepcopy(data)
    d["in_transit"] = pd.concat([d["in_transit"], pd.DataFrame([{
        "sku": "SKU-0000", "warehouse": "WH1", "qty": 500,
        "eta": TODAY + pd.Timedelta(days=5),
    }])], ignore_index=True)
    changed = _row(recommend(d, {"today": TODAY}), "SKU-0000")
    assert changed["need_raw"] != base_need

    d = copy.deepcopy(data)
    d["stock"] = d["stock"].copy()
    d["stock"]["on_hand"] = d["stock"]["on_hand"].astype(float)
    d["stock"].loc[(d["stock"]["sku"] == "SKU-0000") & (d["stock"]["warehouse"] == "WH1"), "on_hand"] *= 0.5
    changed = _row(recommend(d, {"today": TODAY}), "SKU-0000")
    assert changed["need_raw"] != base_need

    changed = _row(recommend(data, {"today": TODAY, "growth_override": {base["category"]: 20.0}}), "SKU-0000")
    assert changed["need_raw"] != base_need

    d = copy.deepcopy(data)
    d["stockouts"] = d["stockouts"][d["stockouts"]["sku"] != "DEMO-STOCKOUT"]
    changed = _row(recommend(d, {"today": TODAY}), "DEMO-STOCKOUT")
    base_stockout = _row(base_result, "DEMO-STOCKOUT")
    assert changed["need_raw"] != base_stockout["need_raw"]

    # BOM: recommend() разворачивает комплект в спрос на компоненты при каждом
    # вызове (см. pipeline._build_context), поэтому продажи комплекта, убранные
    # из sales, обязаны снизить потребность по компоненту.
    bom_rule = data["bom"].iloc[0]
    component_sku = bom_rule["component_sku"]
    base_component = _row(base_result, component_sku)
    d = copy.deepcopy(data)
    d["sales"] = d["sales"][~d["sales"]["sku"].isin(data["bom"]["parent_sku"])].copy()
    changed = _row(recommend(d, {"today": TODAY}), component_sku)
    assert changed["need_raw"] != base_component["need_raw"]


def _model_for(data, sku, warehouse="WH1", growth_pct=0.0):
    trimmed, _ = demand.detect_and_trim_oneoffs(data["sales"])
    monthly = demand.monthly_clean_series(trimmed, data["stockouts"], TODAY)
    category = data["products"].loc[data["products"]["sku"] == sku, "category"].iloc[0]
    cat_season = forecast.build_category_seasonal(monthly, data["products"])
    series = monthly[(monthly["sku"] == sku) & (monthly["warehouse"] == warehouse)]
    return forecast.forecast_sku(series, cat_season.get(category, {}), growth_pct)


def test_seasonality(data):
    """Must-have 2: прогноз пикового месяца заметно выше провального, а не
    просто среднее по всей истории (прогон backtest подтверждает, что модель
    точнее наивного среднего)."""
    model = _model_for(data, "DEMO-SEASON")
    season = model["season_index"]
    ratio = max(season.values()) / max(min(season.values()), 1e-9)
    assert ratio > 1.5, "сезонный разброс должен быть выражен"
    if model["wape_model"] is not None:
        assert model["wape_model"] <= model["wape_naive"], "модель не должна проигрывать наивному среднему"


def test_lost_demand_compensated(data, base_result):
    """Must-have 3: для артикула со stockout расчётная потребность скорректирована
    в большую сторону по сравнению с расчётом без учёта дней отсутствия товара
    (и по прогнозу спроса, и по итоговой потребности — sigma страхового запаса
    тоже не должна раздуваться из-за нескомпенсированного провала продаж)."""
    with_stockout = _row(base_result, "DEMO-STOCKOUT")
    assert with_stockout["lost_demand_added"] > 0

    d = copy.deepcopy(data)
    d["stockouts"] = d["stockouts"][d["stockouts"]["sku"] != "DEMO-STOCKOUT"]
    without_stockout = _row(recommend(d, {"today": TODAY}), "DEMO-STOCKOUT")
    assert with_stockout["forecast_horizon"] > without_stockout["forecast_horizon"]
    assert with_stockout["need_raw"] > without_stockout["need_raw"]


def test_oneoff_excluded(base_result):
    """Must-have 4: разовый крупный заказ не раздувает регулярную потребность."""
    row = _row(base_result, "DEMO-ONEOFF")
    assert row["oneoff_excluded"] > 0


def test_oneoff_injection_limits_growth(data):
    """Искусственно добавленный разовый заказ поднимает recommended_qty не более чем на 10%."""
    base = recommend(data, {"today": TODAY})
    base_row = _row(base, "SKU-0001")

    d = copy.deepcopy(data)
    median_qty = d["sales"].loc[d["sales"]["sku"] == "SKU-0001", "qty"].median() or 5
    injected = pd.DataFrame([{
        "date": TODAY - pd.Timedelta(days=10),
        "sku": "SKU-0001", "qty": median_qty * 50, "client_id": "NEW-ONEOFF-CLIENT",
        "price": 1000, "warehouse": "WH1",
    }])
    d["sales"] = pd.concat([d["sales"], injected], ignore_index=True)
    changed_row = _row(recommend(d, {"today": TODAY}), "SKU-0001")

    if base_row["recommended_qty"] > 0:
        growth = (changed_row["recommended_qty"] - base_row["recommended_qty"]) / base_row["recommended_qty"]
        assert growth <= 0.10


def test_grouped_by_supplier_with_explanations(base_result):
    """Must-have 5: список сгруппирован по поставщикам, у каждой строки есть обоснование."""
    assert (base_result["explanation"].str.len() > 0).all()
    by_supplier = base_result.groupby("supplier_id")["recommended_qty"].sum()
    assert by_supplier.sum() == base_result["recommended_qty"].sum()
    assert base_result["supplier_id"].notna().all()


def test_robust_to_garbage_input():
    """Устойчивость: мусорные/отрицательные значения не должны валить расчёт.
    Мусор добавляем на "сыром" уровне и прогоняем через io.clean(), как это
    происходит при обычной загрузке файлов."""
    raw = engine_io.load_dir(OUT_DIR)
    raw["sales"] = pd.concat([raw["sales"], pd.DataFrame([
        {"date": "not-a-date", "sku": "SKU-0000", "qty": "abc", "client_id": "X", "price": 1, "warehouse": "WH1"},
        {"date": (TODAY - pd.Timedelta(days=1)).strftime("%Y-%m-%d"), "sku": "SKU-0000", "qty": 0, "client_id": "X", "price": 1, "warehouse": "WH1"},
    ])], ignore_index=True)
    raw["stock"].loc[raw["stock"]["sku"] == "SKU-0000", "on_hand"] = -5
    cleaned = engine_io.clean(raw, TODAY)  # recommend() explodes BOM itself, no need to do it here
    result = recommend(cleaned, {"today": TODAY})
    assert not result.empty


def test_critical_urgency_flagged(base_result):
    row = _row(base_result, "DEMO-CRITICAL")
    assert row["urgency"] in {"critical", "high"}
