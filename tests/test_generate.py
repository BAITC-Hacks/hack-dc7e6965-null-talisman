from __future__ import annotations

from pathlib import Path

import pandas as pd


EXPECTED_FILES = {
    "sales.csv",
    "stock.csv",
    "in_transit.csv",
    "stockouts.csv",
    "products.csv",
    "suppliers.csv",
    "growth.csv",
    "bom.csv",
}

EXPECTED_COLUMNS = {
    "sales.csv": {"date", "sku", "qty", "client_id", "price", "warehouse"},
    "stock.csv": {"sku", "warehouse", "on_hand"},
    "in_transit.csv": {"sku", "warehouse", "qty", "eta"},
    "stockouts.csv": {"sku", "warehouse", "start", "end"},
    "products.csv": {"sku", "name", "category", "supplier_id", "pack_size", "moq"},
    "suppliers.csv": {"supplier_id", "name", "lead_time_days", "order_cycle_days"},
    "growth.csv": {"category", "growth_pct"},
    "bom.csv": {"parent_sku", "component_sku", "qty_per"},
}


def _generate_to(directory: Path, seed: int = 42) -> dict[str, Path]:
    from data import generate as generator

    original_output, original_seed = generator.OUT_DIR, generator.SEED
    try:
        generator.OUT_DIR = directory
        generator.SEED = seed
        generator.generate()
    finally:
        generator.OUT_DIR = original_output
        generator.SEED = original_seed
    return {path.name: path for path in directory.glob("*.csv")}


def _csv_bytes(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(directory.glob("*.csv"))}


def test_generate_demo_data_is_deterministic(tmp_path: Path) -> None:
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"

    first = _generate_to(first_dir)
    second = _generate_to(second_dir)

    assert set(first) == EXPECTED_FILES
    assert set(second) == EXPECTED_FILES
    assert _csv_bytes(first_dir) == _csv_bytes(second_dir)


def test_generate_demo_data_writes_all_contract_schemas(tmp_path: Path) -> None:
    output_dir = tmp_path / "demo"
    _generate_to(output_dir)

    for filename, expected_columns in EXPECTED_COLUMNS.items():
        assert set(pd.read_csv(output_dir / filename).columns) == expected_columns


def test_generate_demo_data_contains_contract_and_demo_skus(tmp_path: Path) -> None:
    from data.generate import DEMO_SKUS

    output_dir = tmp_path / "demo"
    _generate_to(output_dir)

    products = pd.read_csv(output_dir / "products.csv")
    sales = pd.read_csv(output_dir / "sales.csv")
    stock = pd.read_csv(output_dir / "stock.csv")

    assert set(DEMO_SKUS).issubset(set(products["sku"]))
    assert len(products) >= 150
    assert sales["warehouse"].nunique() == 2
    assert sales["date"].nunique() >= 1_000
    assert set(stock["warehouse"]) == {"WH1", "WH2"}


def test_reference_skus_encode_demo_scenarios(tmp_path: Path) -> None:
    from data.generate import TODAY

    output_dir = tmp_path / "demo"
    _generate_to(output_dir)

    products = pd.read_csv(output_dir / "products.csv")
    suppliers = pd.read_csv(output_dir / "suppliers.csv")
    stock = pd.read_csv(output_dir / "stock.csv")
    transit = pd.read_csv(output_dir / "in_transit.csv", parse_dates=["eta"])
    sales = pd.read_csv(output_dir / "sales.csv", parse_dates=["date"])
    stockouts = pd.read_csv(output_dir / "stockouts.csv")

    transit_demo = transit.loc[
        (transit["sku"] == "DEMO-TRANSIT") & (transit["eta"] > TODAY)
    ]
    recent = sales.loc[
        (sales["sku"] == "DEMO-TRANSIT")
        & (sales["date"] >= TODAY - pd.Timedelta(days=90)),
        "qty",
    ]
    assert not transit_demo.empty
    assert float(transit_demo["qty"].max()) >= float(recent.sum()) / 90 * 45

    critical = products.loc[products["sku"] == "DEMO-CRITICAL"].merge(
        suppliers, on="supplier_id", validate="many_to_one"
    )
    critical_daily = (
        sales.loc[
            (sales["sku"] == "DEMO-CRITICAL")
            & (sales["date"] >= TODAY - pd.Timedelta(days=90)),
            "qty",
        ].sum()
        / 90
    )
    critical_stock = stock.loc[
        (stock["sku"] == "DEMO-CRITICAL") & (stock["warehouse"] == "WH1"),
        "on_hand",
    ].iloc[0]
    assert int(critical.iloc[0]["lead_time_days"]) >= 30
    assert critical_stock / critical_daily <= 6

    outage = stockouts.loc[stockouts["sku"] == "DEMO-STOCKOUT"].iloc[0]
    outage_sales = sales.loc[
        (sales["sku"] == "DEMO-STOCKOUT")
        & (sales["date"] >= outage["start"])
        & (sales["date"] <= outage["end"])
    ]
    assert outage_sales.loc[outage_sales["warehouse"] == outage["warehouse"]].empty
    assert not outage_sales.loc[outage_sales["warehouse"] != outage["warehouse"]].empty


def test_growth_defaults_to_zero_and_demo_growth_is_organic(tmp_path: Path) -> None:
    output_dir = tmp_path / "demo"
    _generate_to(output_dir)

    growth = pd.read_csv(output_dir / "growth.csv")
    sales = pd.read_csv(output_dir / "sales.csv", parse_dates=["date"])
    demo = sales.loc[sales["sku"] == "DEMO-GROWTH"].copy()
    monthly = demo.groupby(demo["date"].dt.to_period("M"))["qty"].sum()

    assert growth["growth_pct"].eq(0).all()
    assert monthly.tail(6).mean() > monthly.head(6).mean()


def test_bom_models_three_multi_component_kits(tmp_path: Path) -> None:
    output_dir = tmp_path / "demo"
    _generate_to(output_dir)

    bom = pd.read_csv(output_dir / "bom.csv")
    component_counts = bom.groupby("parent_sku")["component_sku"].nunique()

    assert len(component_counts) == 3
    assert component_counts.min() >= 3
    assert bom["qty_per"].gt(0).all()
