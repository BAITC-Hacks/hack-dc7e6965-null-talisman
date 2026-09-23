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


def _csv_bytes(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(directory.glob("*.csv"))}


def test_generate_demo_data_is_deterministic(tmp_path: Path) -> None:
    from data.generate import generate_demo_data

    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first = generate_demo_data(first_dir, seed=42)
    second = generate_demo_data(second_dir, seed=42)

    assert set(first) == EXPECTED_FILES
    assert set(second) == EXPECTED_FILES
    assert _csv_bytes(first_dir) == _csv_bytes(second_dir)


def test_generate_demo_data_writes_all_contract_schemas(tmp_path: Path) -> None:
    from data.generate import generate_demo_data

    output_dir = tmp_path / "demo"
    generate_demo_data(output_dir, seed=42)

    for filename, expected_columns in EXPECTED_COLUMNS.items():
        assert set(pd.read_csv(output_dir / filename).columns) == expected_columns


def test_generate_demo_data_contains_contract_and_demo_skus(tmp_path: Path) -> None:
    from data.generate import DEMO_SKUS, generate_demo_data

    output_dir = tmp_path / "demo"
    generate_demo_data(output_dir, seed=42)

    products = pd.read_csv(output_dir / "products.csv")
    sales = pd.read_csv(output_dir / "sales.csv")
    stock = pd.read_csv(output_dir / "stock.csv")

    assert set(DEMO_SKUS).issubset(set(products["sku"]))
    assert {"date", "sku", "qty", "client_id", "price", "warehouse"} == set(
        sales.columns
    )
    assert {"sku", "warehouse", "on_hand"} == set(stock.columns)
    assert len(products) >= 150
    assert sales["warehouse"].nunique() == 2
    assert sales["date"].nunique() >= 1_000


def test_reference_skus_encode_demo_scenarios(tmp_path: Path) -> None:
    from data.generate import generate_demo_data

    output_dir = tmp_path / "demo"
    generate_demo_data(output_dir, seed=42)

    products = pd.read_csv(output_dir / "products.csv")
    suppliers = pd.read_csv(output_dir / "suppliers.csv")
    stock = pd.read_csv(output_dir / "stock.csv")
    transit = pd.read_csv(output_dir / "in_transit.csv")
    sales = pd.read_csv(output_dir / "sales.csv", parse_dates=["date"])
    stockouts = pd.read_csv(output_dir / "stockouts.csv")

    transit_demo = transit.loc[transit["sku"] == "DEMO-TRANSIT"]
    assert len(transit_demo) == 1
    assert float(transit_demo.iloc[0]["qty"]) == 2_000
    assert pd.Timestamp(transit_demo.iloc[0]["eta"]) > pd.Timestamp("2026-09-23")

    critical = (
        products.loc[products["sku"] == "DEMO-CRITICAL"]
        .merge(suppliers, on="supplier_id", validate="many_to_one")
    )
    assert int(critical.iloc[0]["lead_time_days"]) >= 30
    assert stock.loc[stock["sku"] == "DEMO-CRITICAL", "on_hand"].max() <= 5

    outage = stockouts.loc[stockouts["sku"] == "DEMO-STOCKOUT"].iloc[0]
    outage_sales = sales.loc[
        (sales["sku"] == "DEMO-STOCKOUT")
        & (sales["date"] >= outage["start"])
        & (sales["date"] <= outage["end"])
    ]
    assert outage_sales.loc[outage_sales["warehouse"] == outage["warehouse"]].empty
    assert not outage_sales.loc[outage_sales["warehouse"] != outage["warehouse"]].empty


def test_growth_defaults_to_zero_and_new_skus_have_short_history(tmp_path: Path) -> None:
    from data.generate import NEW_SKUS, generate_demo_data

    output_dir = tmp_path / "demo"
    generate_demo_data(output_dir, seed=42)

    growth = pd.read_csv(output_dir / "growth.csv")
    sales = pd.read_csv(output_dir / "sales.csv", parse_dates=["date"])
    new_sales = sales.loc[sales["sku"].isin(NEW_SKUS)]

    assert growth["growth_pct"].eq(0).all()
    assert set(NEW_SKUS).issubset(set(new_sales["sku"]))
    assert new_sales["date"].min() >= pd.Timestamp("2026-08-01")


def test_bom_models_three_multi_component_kits(tmp_path: Path) -> None:
    from data.generate import generate_demo_data

    output_dir = tmp_path / "demo"
    generate_demo_data(output_dir, seed=42)

    bom = pd.read_csv(output_dir / "bom.csv")
    component_counts = bom.groupby("parent_sku")["component_sku"].nunique()

    assert len(component_counts) == 3
    assert component_counts.min() >= 3
    assert bom["qty_per"].gt(0).all()
