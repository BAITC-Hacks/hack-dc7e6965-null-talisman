from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


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


@pytest.fixture(scope="module")
def demo_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from data import generate as generator

    output = tmp_path_factory.mktemp("pipeline-demo")
    original_output = generator.OUT_DIR
    try:
        generator.OUT_DIR = output
        generator.generate()
    finally:
        generator.OUT_DIR = original_output
    return output


@pytest.fixture(scope="module")
def prepared_data(demo_dir: Path) -> dict[str, pd.DataFrame]:
    from data.generate import TODAY
    from engine.io import load_and_prepare

    data, warnings = load_and_prepare(demo_dir, TODAY)
    assert not warnings
    return data


def test_recommend_returns_stable_ui_contract(prepared_data) -> None:
    from data.generate import TODAY
    from engine.pipeline import recommend

    result = recommend(prepared_data, params={"today": TODAY})

    assert isinstance(result, pd.DataFrame)
    assert result.columns.tolist() == EXPECTED_COLUMNS
    assert not result.empty
    assert result["explanation"].str.strip().ne("").all()
    assert set(result["urgency"]).issubset({"critical", "high", "normal"})


def test_recommend_returns_a_fresh_dataframe(prepared_data) -> None:
    from data.generate import TODAY
    from engine.pipeline import recommend

    first = recommend(prepared_data, params={"today": TODAY})
    original = int(first.loc[0, "recommended_qty"])
    first.loc[0, "recommended_qty"] = original + 999

    second = recommend(prepared_data, params={"today": TODAY})

    assert int(second.loc[0, "recommended_qty"]) == original


def test_ui_engine_entrypoints_are_compatible(demo_dir: Path) -> None:
    from engine.io import load_data
    from engine.pipeline import sku_series

    data, warnings = load_data(demo_dir)
    assert not warnings

    oneoff = sku_series(data, "DEMO-ONEOFF", "WH1")
    stockout = sku_series(data, "DEMO-STOCKOUT", "WH1")

    assert oneoff.columns.tolist() == [
        "month", "raw", "clean", "forecast", "oneoff", "stockout_days"
    ]
    assert oneoff["oneoff"].max() > 0
    assert stockout["stockout_days"].max() > 0


def test_real_engine_connects_to_streamlit(demo_dir, monkeypatch):
    from app import backend
    from streamlit.testing.v1 import AppTest

    files = []
    for path in sorted(demo_dir.glob("*.csv")):
        table = pd.read_csv(path)
        if "sku" in table:
            table = table.loc[table["sku"] == "DEMO-CRITICAL"]
        if path.stem == "bom":
            table = table.iloc[:0]
        files.append((path.name, table.to_csv(index=False).encode("utf-8")))
    monkeypatch.setattr(backend, "demo_files", lambda: tuple(files))
    backend.load_files.clear()
    backend.calculate.clear()
    backend.series.clear()
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(str(root / "app/streamlit_app.py"), default_timeout=60).run()
    assert not app.exception
    button = next(item for item in app.button if item.label == "Рассчитать")
    assert not button.disabled
    button.click().run()
    assert not app.exception
    assert not app.session_state["result"].empty
    assert len(app.get("plotly_chart")) > 0
    assert not any("Не удалось" in item.value for item in app.warning)


def test_loader_reports_missing_required_column(tmp_path):
    from engine.io import REQUIRED_COLUMNS, load_data

    for name, columns in REQUIRED_COLUMNS.items():
        table = pd.DataFrame(columns=columns)
        if name == "sales":
            table = table.drop(columns="date")
        table.to_csv(tmp_path / f"{name}.csv", index=False)
    with pytest.raises(ValueError, match="sales.*date"):
        load_data(tmp_path)
