"""Загрузка, валидация и обезличивание входных данных.

Контракт входных файлов — docs/PLAN.md, раздел 3.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = {
    "sales": ["date", "sku", "qty", "client_id", "price", "warehouse"],
    "stock": ["sku", "warehouse", "on_hand"],
    "in_transit": ["sku", "warehouse", "qty", "eta"],
    "stockouts": ["sku", "warehouse", "start", "end"],
    "products": ["sku", "name", "category", "supplier_id", "pack_size", "moq"],
    "suppliers": ["supplier_id", "name", "lead_time_days", "order_cycle_days"],
    "growth": ["category", "growth_pct"],
    "bom": ["parent_sku", "component_sku", "qty_per"],
}

# файлы, которые допустимо отсутствовать (используем пустые/дефолтные значения)
OPTIONAL = {"in_transit", "stockouts", "growth", "bom"}

DEFAULT_SALT = "hackalem-null-talisman"


class ValidationIssue(Exception):
    """Собирает читаемые предупреждения по загрузке, не падает на них."""


def hash_client_id(client_id: str, salt: str | None = None) -> str:
    salt = salt if salt is not None else os.environ.get("CLIENT_HASH_SALT") or DEFAULT_SALT
    return hashlib.sha256((salt + str(client_id)).encode("utf-8")).hexdigest()[:10]


def _empty_frame(name: str) -> pd.DataFrame:
    return pd.DataFrame(columns=REQUIRED_COLUMNS[name])


def load_dir(source_dir: str | Path) -> dict[str, pd.DataFrame]:
    """Читает CSV из директории. Отсутствующие опциональные файлы -> пустой DataFrame."""
    source_dir = Path(source_dir)
    data = {}
    for name in REQUIRED_COLUMNS:
        path = source_dir / f"{name}.csv"
        if path.exists():
            data[name] = pd.read_csv(path)
        elif name in OPTIONAL:
            data[name] = _empty_frame(name)
        else:
            raise FileNotFoundError(f"Обязательный файл отсутствует: {path}")
    return data


def validate(data: dict[str, pd.DataFrame]) -> list[str]:
    """Возвращает список предупреждений. Не бросает исключения на плохих данных —
    вызывающий код решает, показывать ли их пользователю."""
    warnings: list[str] = []
    for name, cols in REQUIRED_COLUMNS.items():
        df = data.get(name)
        if df is None:
            warnings.append(f"Файл {name} отсутствует")
            continue
        missing = [c for c in cols if c not in df.columns]
        if missing:
            warnings.append(f"{name}.csv: отсутствуют колонки {missing}")
    sales = data.get("sales")
    if sales is not None and not sales.empty:
        if "qty" in sales.columns and not pd.to_numeric(sales["qty"], errors="coerce").notna().all():
            warnings.append("sales.csv: есть нечисловые значения qty — такие строки будут отброшены")
    return warnings


def clean(data: dict[str, pd.DataFrame], today: pd.Timestamp, salt: str | None = None) -> dict[str, pd.DataFrame]:
    """Приводит типы, обезличивает клиентов, отбрасывает мусор. Возвращает новый dict."""
    out = {k: v.copy() for k, v in data.items()}

    sales = out["sales"]
    if not sales.empty:
        sales["date"] = pd.to_datetime(sales["date"], errors="coerce")
        sales["qty"] = pd.to_numeric(sales["qty"], errors="coerce")
        sales["price"] = pd.to_numeric(sales.get("price"), errors="coerce")
        sales = sales.dropna(subset=["date", "sku", "qty"])
        sales = sales[sales["qty"] != 0]
        sales = sales[sales["date"] <= today]
        sales["client_id"] = sales["client_id"].fillna("UNKNOWN").astype(str).map(
            lambda c: hash_client_id(c, salt)
        )
        sales = sales.drop_duplicates()
    out["sales"] = sales.reset_index(drop=True)

    stock = out["stock"]
    if not stock.empty:
        stock["on_hand"] = pd.to_numeric(stock["on_hand"], errors="coerce").fillna(0).clip(lower=0)
    out["stock"] = stock

    in_transit = out["in_transit"]
    if not in_transit.empty:
        in_transit["eta"] = pd.to_datetime(in_transit["eta"], errors="coerce")
        in_transit["qty"] = pd.to_numeric(in_transit["qty"], errors="coerce").fillna(0)
        in_transit = in_transit.dropna(subset=["eta"])
    out["in_transit"] = in_transit

    stockouts = out["stockouts"]
    if not stockouts.empty:
        stockouts["start"] = pd.to_datetime(stockouts["start"], errors="coerce")
        stockouts["end"] = pd.to_datetime(stockouts["end"], errors="coerce")
        stockouts = stockouts.dropna(subset=["start", "end"])
    out["stockouts"] = stockouts

    products = out["products"]
    if not products.empty:
        products["pack_size"] = pd.to_numeric(products["pack_size"], errors="coerce").fillna(1).clip(lower=1)
        products["moq"] = pd.to_numeric(products["moq"], errors="coerce").fillna(0).clip(lower=0)
    out["products"] = products

    suppliers = out["suppliers"]
    if not suppliers.empty:
        suppliers["lead_time_days"] = pd.to_numeric(suppliers["lead_time_days"], errors="coerce").fillna(14)
        suppliers["order_cycle_days"] = pd.to_numeric(suppliers["order_cycle_days"], errors="coerce").fillna(14)
    out["suppliers"] = suppliers

    growth = out["growth"]
    if not growth.empty:
        growth["growth_pct"] = pd.to_numeric(growth["growth_pct"], errors="coerce").fillna(0.0)
    out["growth"] = growth

    bom = out["bom"]
    if not bom.empty:
        bom["qty_per"] = pd.to_numeric(bom["qty_per"], errors="coerce").fillna(1).clip(lower=0)
    out["bom"] = bom

    return out


def explode_bom(sales: pd.DataFrame, bom: pd.DataFrame) -> pd.DataFrame:
    """Продажи комплекта (parent_sku) дают дополнительный спрос на компоненты.
    Прямые продажи компонентов остаются нетронутыми; строки от BOM размечаются
    client_id='BOM' и исключаются из поиска разовых заказов (см. demand.py)."""
    if bom.empty or sales.empty:
        return sales
    extra_rows = []
    for _, rule in bom.iterrows():
        parent_sales = sales[sales["sku"] == rule["parent_sku"]]
        if parent_sales.empty:
            continue
        derived = parent_sales.copy()
        derived["sku"] = rule["component_sku"]
        derived["qty"] = derived["qty"] * rule["qty_per"]
        derived["client_id"] = "BOM"
        derived["price"] = 0.0
        extra_rows.append(derived)
    if not extra_rows:
        return sales
    return pd.concat([sales, *extra_rows], ignore_index=True)


def load_and_prepare(source_dir: str | Path, today: pd.Timestamp, salt: str | None = None):
    """Полный конвейер загрузки: читает, валидирует, чистит, разворачивает BOM.
    Возвращает (data, warnings)."""
    raw = load_dir(source_dir)
    warnings = validate(raw)
    cleaned = clean(raw, today, salt)
    cleaned["sales"] = explode_bom(cleaned["sales"], cleaned["bom"])
    return cleaned, warnings
