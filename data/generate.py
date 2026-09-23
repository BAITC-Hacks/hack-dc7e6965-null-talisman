"""Детерминированная генерация синтетических данных для демо.

Запуск: python -m data.generate
Пишет CSV в data/demo/. Ничего не делает, если data/demo/ уже не пустая
(удалите папку вручную, если нужно перегенерировать).

Контракт колонок описан в docs/PLAN.md, раздел 3.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
TODAY = pd.Timestamp("2026-09-23")
HISTORY_YEARS = 3
OUT_DIR = Path(__file__).resolve().parent / "demo"

CATEGORIES = {
    # category -> (seasonal profile, base level range, popularity weight)
    "Кабель": "summer",
    "Автоматические выключатели": "flat",
    "Розетки и выключатели": "flat",
    "Светильники": "winter",
    "Щиты и боксы": "summer",
    "Лампы": "winter",
    "УЗО и дифавтоматы": "flat",
    "Кабель-каналы": "summer",
}

SEASONAL_PROFILES = {
    # 12 monthly multipliers, Jan..Dec, mean ~1
    "summer": [0.65, 0.65, 0.8, 1.05, 1.35, 1.55, 1.6, 1.45, 1.1, 0.85, 0.65, 0.6],
    "winter": [1.55, 1.4, 1.05, 0.8, 0.6, 0.55, 0.55, 0.6, 0.8, 1.1, 1.5, 1.7],
    "flat": [0.95, 0.95, 1.0, 1.0, 1.05, 1.05, 1.0, 1.0, 1.0, 1.0, 1.0, 1.05],
}

SUPPLIERS = [
    ("SUP1", "ЭлектроСнаб КЗ", 10, 14),
    ("SUP2", "КабельОпт", 21, 14),
    ("SUP3", "СветТорг", 14, 7),
    ("SUP4", "МеталлКомплект", 30, 21),
    ("SUP5", "УЗО-Дистрибуция", 18, 14),
    ("SUP6", "ИмпортЭлектро", 60, 30),
]

DEMO_SKUS = {
    "DEMO-SEASON": ("Светильники", "winter"),
    "DEMO-STOCKOUT": ("Кабель", "summer"),
    "DEMO-ONEOFF": ("Автоматические выключатели", "flat"),
    "DEMO-GROWTH": ("Розетки и выключатели", "flat"),
    "DEMO-TRANSIT": ("УЗО и дифавтоматы", "flat"),
    "DEMO-CRITICAL": ("Кабель-каналы", "summer"),
}

WAREHOUSES = ["WH1", "WH2"]
N_REGULAR_SKUS = 144  # + 6 demo = 150
N_CLIENTS = 300


def _rng():
    return np.random.default_rng(SEED)


def client_hash(client_id: str, salt: str = "") -> str:
    return hashlib.sha256((salt + client_id).encode("utf-8")).hexdigest()[:10]


def _build_products(rng) -> pd.DataFrame:
    rows = []
    cats = list(CATEGORIES.keys())
    for i in range(N_REGULAR_SKUS):
        cat = cats[i % len(cats)]
        sup = SUPPLIERS[rng.integers(0, len(SUPPLIERS))][0]
        pack = int(rng.choice([1, 5, 10, 20, 50]))
        moq = int(rng.choice([0, 0, pack, pack * 2, pack * 5]))
        rows.append({
            "sku": f"SKU-{i:04d}",
            "name": f"{cat} тип {i % 23 + 1}",
            "category": cat,
            "supplier_id": sup,
            "pack_size": pack,
            "moq": moq,
        })
    demo_supplier_cycle = ["SUP1", "SUP2", "SUP3", "SUP4", "SUP5", "SUP6"]
    for i, (sku, (cat, _profile)) in enumerate(DEMO_SKUS.items()):
        rows.append({
            "sku": sku,
            "name": f"{cat} — демо-позиция ({sku})",
            "category": cat,
            "supplier_id": demo_supplier_cycle[i % len(demo_supplier_cycle)],
            "pack_size": 10 if sku != "DEMO-CRITICAL" else 1,
            "moq": 0,
        })
    # BOM kit components + 3 assembled kits
    for j in range(3):
        parent = f"KIT-{j:02d}"
        rows.append({
            "sku": parent,
            "name": f"Щит в сборе, комплект {j + 1}",
            "category": "Щиты и боксы",
            "supplier_id": SUPPLIERS[j % len(SUPPLIERS)][0],
            "pack_size": 1,
            "moq": 0,
        })
    return pd.DataFrame(rows)


def _seasonal_multiplier(category: str, month: int) -> float:
    profile = SEASONAL_PROFILES[CATEGORIES.get(category, "flat")]
    return profile[month - 1]


def _simulate_sku_sales(rng, sku, category, base_level, growth_pct_month,
                         intermittent, dates) -> list[dict]:
    """Simulate daily sale-line events for one sku across the full history."""
    rows = []
    months_elapsed = 0
    cur_month = None
    level = base_level
    for d in dates:
        if cur_month != (d.year, d.month):
            cur_month = (d.year, d.month)
            months_elapsed += 1
        trend_mult = (1 + growth_pct_month / 100) ** months_elapsed
        season = _seasonal_multiplier(category, d.month)
        days_in_month = d.days_in_month
        monthly_demand = level * trend_mult * season
        if intermittent:
            monthly_demand *= 0.35
        daily_mean = max(monthly_demand / days_in_month, 0.01)
        if intermittent:
            # sparse: most days zero, occasional bigger purchase
            if rng.random() < 0.12:
                qty = max(1, int(rng.poisson(daily_mean * 8)))
                rows.append(_sale_row(rng, d, sku, qty))
            continue
        n_lines = rng.poisson(max(daily_mean / 6, 0.02))  # a few order lines/day
        for _ in range(n_lines):
            qty = max(1, int(rng.poisson(6) + 1))
            rows.append(_sale_row(rng, d, sku, qty))
    return rows


def _sale_row(rng, date, sku, qty, warehouse=None, client_id=None, price=None):
    return {
        "date": date.strftime("%Y-%m-%d"),
        "sku": sku,
        "qty": qty,
        "client_id": client_id or f"C{rng.integers(1, N_CLIENTS + 1):04d}",
        "price": price if price is not None else round(float(rng.uniform(900, 15000)), 2),
        "warehouse": warehouse or (WAREHOUSES[0] if rng.random() < 0.6 else WAREHOUSES[1]),
    }


def generate() -> None:
    if OUT_DIR.exists() and any(OUT_DIR.glob("*.csv")):
        print(f"{OUT_DIR} уже содержит данные, пропускаю генерацию.")
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = _rng()

    products = _build_products(rng)
    dates = pd.date_range(TODAY - pd.DateOffset(years=HISTORY_YEARS), TODAY, freq="D")

    growth_skus = set(products["sku"].sample(frac=0.15, random_state=SEED))
    growth_skus.add("DEMO-GROWTH")
    intermittent_skus = set(
        products.loc[~products["sku"].str.startswith(("DEMO", "KIT"))]
        .sample(frac=0.12, random_state=SEED + 1)["sku"]
    )

    all_sales = []
    for _, prod in products.iterrows():
        sku = prod["sku"]
        cat = prod["category"]
        base_level = float(rng.uniform(40, 260))
        growth = float(rng.uniform(2, 4)) if sku in growth_skus else 0.0
        intermittent = sku in intermittent_skus
        sku_sales = _simulate_sku_sales(
            rng, sku, cat, base_level, growth, intermittent, dates
        )
        all_sales.extend(sku_sales)

    sales = pd.DataFrame(all_sales)

    # --- DEMO-ONEOFF: inject one clearly one-off large order from a client
    # that never buys this sku otherwise (fails robust-z + irregular-client test)
    median_line = sales.loc[sales["sku"] == "DEMO-ONEOFF", "qty"].median()
    oneoff_date = TODAY - pd.Timedelta(days=45)
    sales = pd.concat([sales, pd.DataFrame([_sale_row(
        rng, oneoff_date, "DEMO-ONEOFF", int(max(median_line, 5) * 20),
        client_id="C9001", warehouse="WH1",
    )])], ignore_index=True)

    # sprinkle a few generic one-off large orders across random skus too
    regular_skus = products.loc[
        ~products["sku"].str.startswith(("DEMO", "KIT")), "sku"
    ].sample(n=6, random_state=SEED + 2)
    for sku in regular_skus:
        med = sales.loc[sales["sku"] == sku, "qty"].median()
        if pd.isna(med) or med <= 0:
            continue
        d = TODAY - pd.Timedelta(days=int(rng.integers(20, 300)))
        sales = pd.concat([sales, pd.DataFrame([_sale_row(
            rng, d, sku, int(med * rng.uniform(15, 30)), client_id=f"C{9100 + int(rng.integers(0, 50)):04d}",
        )])], ignore_index=True)

    # --- stockouts: DEMO-STOCKOUT + a handful of random skus
    stockout_rows = []
    so_start = TODAY - pd.Timedelta(days=50)
    so_end = TODAY - pd.Timedelta(days=29)
    stockout_rows.append({"sku": "DEMO-STOCKOUT", "warehouse": "WH1",
                           "start": so_start.strftime("%Y-%m-%d"),
                           "end": so_end.strftime("%Y-%m-%d")})
    # suppress actual sales for DEMO-STOCKOUT/WH1 during the stockout window
    mask = (
        (sales["sku"] == "DEMO-STOCKOUT")
        & (sales["warehouse"] == "WH1")
        & (sales["date"] >= so_start.strftime("%Y-%m-%d"))
        & (sales["date"] <= so_end.strftime("%Y-%m-%d"))
    )
    sales = sales.loc[~mask].reset_index(drop=True)

    for sku in products.loc[~products["sku"].str.startswith(("DEMO", "KIT")), "sku"].sample(n=5, random_state=SEED + 3):
        start = TODAY - pd.Timedelta(days=int(rng.integers(60, 500)))
        end = start + pd.Timedelta(days=int(rng.integers(7, 21)))
        stockout_rows.append({"sku": sku, "warehouse": rng.choice(WAREHOUSES),
                               "start": start.strftime("%Y-%m-%d"),
                               "end": end.strftime("%Y-%m-%d")})
    stockouts = pd.DataFrame(stockout_rows)

    # --- current stock levels: realistic 35-90 days of cover per sku/warehouse
    recent = sales[sales["date"] >= (TODAY - pd.Timedelta(days=90)).strftime("%Y-%m-%d")]
    daily_avg = recent.groupby("sku")["qty"].sum() / 90.0
    daily_avg_by_warehouse = recent.groupby(["sku", "warehouse"])["qty"].sum() / 90.0
    stock_rows = []
    for _, prod in products.iterrows():
        sku = prod["sku"]
        avg = float(daily_avg.get(sku, 1.0)) or 1.0
        for wh in WAREHOUSES:
            warehouse_avg = float(daily_avg_by_warehouse.get((sku, wh), avg * 0.5)) or avg * 0.5
            days_cover = float(rng.uniform(35, 90))
            on_hand = max(0, round(warehouse_avg * days_cover))
            stock_rows.append({"sku": sku, "warehouse": wh, "on_hand": int(on_hand)})
    stock = pd.DataFrame(stock_rows)
    # DEMO-CRITICAL: ~5 days of cover, supplier lead time 30d -> definitely critical
    crit_avg = float(daily_avg.get("DEMO-CRITICAL", 5.0)) or 5.0
    stock.loc[(stock["sku"] == "DEMO-CRITICAL") & (stock["warehouse"] == "WH1"), "on_hand"] = max(1, round(crit_avg * 5))
    # DEMO-TRANSIT: on_hand low but a big shipment is already coming
    stock.loc[(stock["sku"] == "DEMO-TRANSIT") & (stock["warehouse"] == "WH1"), "on_hand"] = max(1, round(daily_avg.get("DEMO-TRANSIT", 5.0) * 3))

    # --- in-transit shipments for ~30% of skus
    transit_rows = []
    transit_skus = products["sku"].sample(frac=0.30, random_state=SEED + 4).tolist()
    for sku in transit_skus:
        eta = TODAY + pd.Timedelta(days=int(rng.integers(3, 45)))
        qty = int(max(daily_avg.get(sku, 5.0), 1) * rng.uniform(10, 25))
        transit_rows.append({"sku": sku, "warehouse": WAREHOUSES[0], "qty": qty,
                              "eta": eta.strftime("%Y-%m-%d")})
    # a couple of overdue shipments (ETA already passed)
    for sku in products["sku"].sample(n=3, random_state=SEED + 5):
        eta = TODAY - pd.Timedelta(days=int(rng.integers(2, 15)))
        qty = int(max(daily_avg.get(sku, 5.0), 1) * rng.uniform(5, 15))
        transit_rows.append({"sku": sku, "warehouse": WAREHOUSES[0], "qty": qty,
                              "eta": eta.strftime("%Y-%m-%d")})
    # DEMO-TRANSIT: a large future shipment covering forecast need
    demo_avg = float(daily_avg.get("DEMO-TRANSIT", 5.0)) or 5.0
    transit_rows.append({"sku": "DEMO-TRANSIT", "warehouse": "WH1",
                          "qty": int(demo_avg * 60),
                          "eta": (TODAY + pd.Timedelta(days=10)).strftime("%Y-%m-%d")})
    in_transit = pd.DataFrame(transit_rows)

    suppliers = pd.DataFrame(SUPPLIERS, columns=["supplier_id", "name", "lead_time_days", "order_cycle_days"])
    growth = pd.DataFrame({"category": list(CATEGORIES.keys()), "growth_pct": 0.0})

    bom_rows = []
    kit_component_pool = products.loc[
        products["category"].isin(["Автоматические выключатели", "УЗО и дифавтоматы", "Щиты и боксы"])
        & ~products["sku"].str.startswith("KIT"),
        "sku",
    ].tolist()
    for j in range(3):
        parent = f"KIT-{j:02d}"
        comps = rng.choice(kit_component_pool, size=3, replace=False)
        for comp in comps:
            bom_rows.append({"parent_sku": parent, "component_sku": comp,
                              "qty_per": int(rng.integers(1, 4))})
        # a few kit sales so the BOM explosion has something to explode
        for _ in range(15):
            d = TODAY - pd.Timedelta(days=int(rng.integers(1, 600)))
            sales = pd.concat([sales, pd.DataFrame([_sale_row(rng, d, parent, int(rng.integers(1, 5)))])], ignore_index=True)
    bom = pd.DataFrame(bom_rows)

    sales = sales.sort_values("date").reset_index(drop=True)

    products.to_csv(OUT_DIR / "products.csv", index=False)
    suppliers.to_csv(OUT_DIR / "suppliers.csv", index=False)
    sales.to_csv(OUT_DIR / "sales.csv", index=False)
    stock.to_csv(OUT_DIR / "stock.csv", index=False)
    in_transit.to_csv(OUT_DIR / "in_transit.csv", index=False)
    stockouts.to_csv(OUT_DIR / "stockouts.csv", index=False)
    growth.to_csv(OUT_DIR / "growth.csv", index=False)
    bom.to_csv(OUT_DIR / "bom.csv", index=False)

    print(f"Сгенерировано: {len(products)} sku, {len(sales)} строк продаж -> {OUT_DIR}")


if __name__ == "__main__":
    generate()
