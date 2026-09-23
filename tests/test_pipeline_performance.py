from __future__ import annotations

import pandas as pd

from engine import pipeline


def _two_category_data() -> dict[str, pd.DataFrame]:
    months = pd.period_range("2024-01", "2026-08", freq="M")
    sales_rows = []
    for sku, base in (("A-1", 10), ("B-1", 20)):
        for index, month in enumerate(months):
            sales_rows.append(
                {
                    "date": month.start_time + pd.Timedelta(days=5),
                    "sku": sku,
                    "qty": base + index % 3,
                    "client_id": f"client-{sku}",
                    "price": 100.0,
                    "warehouse": "WH1",
                }
            )

    return {
        "sales": pd.DataFrame(sales_rows),
        "stock": pd.DataFrame(
            [
                {"sku": "A-1", "warehouse": "WH1", "on_hand": 10},
                {"sku": "B-1", "warehouse": "WH1", "on_hand": 10},
            ]
        ),
        "in_transit": pd.DataFrame(columns=["sku", "warehouse", "qty", "eta"]),
        "stockouts": pd.DataFrame(columns=["sku", "warehouse", "start", "end"]),
        "products": pd.DataFrame(
            [
                {
                    "sku": "A-1",
                    "name": "Category A product",
                    "category": "A",
                    "supplier_id": "SUP-A",
                    "pack_size": 1,
                    "moq": 0,
                },
                {
                    "sku": "B-1",
                    "name": "Category B product",
                    "category": "B",
                    "supplier_id": "SUP-B",
                    "pack_size": 1,
                    "moq": 0,
                },
            ]
        ),
        "suppliers": pd.DataFrame(
            [
                {"supplier_id": "SUP-A", "name": "Supplier A", "lead_time_days": 10, "order_cycle_days": 7},
                {"supplier_id": "SUP-B", "name": "Supplier B", "lead_time_days": 10, "order_cycle_days": 7},
            ]
        ),
        "growth": pd.DataFrame(columns=["category", "growth_pct"]),
        "bom": pd.DataFrame(columns=["parent_sku", "component_sku", "qty_per"]),
    }


def _capture_oneoff_input(monkeypatch) -> list[set[str]]:
    captured: list[set[str]] = []
    original = pipeline.demand.detect_and_trim_oneoffs

    def spy(sales: pd.DataFrame):
        captured.append(set(sales["sku"]))
        return original(sales)

    monkeypatch.setattr(pipeline.demand, "detect_and_trim_oneoffs", spy)
    return captured


def test_recommend_builds_context_only_for_selected_category(monkeypatch) -> None:
    data = _two_category_data()
    captured = _capture_oneoff_input(monkeypatch)

    result = pipeline.recommend(
        data,
        {"today": "2026-09-23", "category": "A"},
    )

    assert set(result["sku"]) == {"A-1"}
    assert captured == [{"A-1"}]


def test_sku_series_builds_context_only_for_target_category(monkeypatch) -> None:
    data = _two_category_data()
    captured = _capture_oneoff_input(monkeypatch)

    result = pipeline.sku_series(
        data,
        "A-1",
        "WH1",
        today="2026-09-23",
    )

    assert not result.empty
    assert captured == [{"A-1"}]
