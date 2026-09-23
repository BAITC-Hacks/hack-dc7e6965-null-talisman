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
