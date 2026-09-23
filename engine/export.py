"""Экспорт утверждённого заказа для 1С: XLSX (лист на поставщика) и CSV.
docs/PLAN.md, раздел 4, шаг 6.
"""
from __future__ import annotations

import io
import re

import pandas as pd

EXPORT_COLUMNS = {
    "sku": "Артикул",
    "name": "Номенклатура",
    "warehouse": "Склад",
    "recommended_qty": "Количество",
    "unit": "Ед.",
    "supplier_name": "Поставщик",
    "urgency": "Срочность",
    "explanation": "Обоснование",
}

URGENCY_LABELS = {"critical": "Критично", "high": "Высокая", "normal": "Обычная", "none": "—"}


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["unit"] = "шт"
    out["urgency"] = out["urgency"].map(URGENCY_LABELS).fillna(out["urgency"])
    return out[list(EXPORT_COLUMNS.keys())].rename(columns=EXPORT_COLUMNS)


def _sheet_name(name: str, used: set[str]) -> str:
    safe = re.sub(r"[\[\]\:\*\?/\\]", " ", str(name)).strip()[:31] or "Поставщик"
    candidate = safe
    i = 2
    while candidate in used:
        candidate = f"{safe[:28]}_{i}"
        i += 1
    used.add(candidate)
    return candidate


def export_xlsx(df: pd.DataFrame) -> bytes:
    """Один лист на поставщика. Возвращает содержимое файла (bytes)."""
    prepared = _prep(df)
    buf = io.BytesIO()
    used_names: set[str] = set()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        if prepared.empty:
            prepared.to_excel(writer, sheet_name="Заказ", index=False)
        else:
            for supplier, grp in prepared.groupby("Поставщик"):
                grp.drop(columns=["Поставщик"]).to_excel(
                    writer, sheet_name=_sheet_name(supplier, used_names), index=False
                )
    return buf.getvalue()


def export_csv(df: pd.DataFrame) -> bytes:
    """CSV с ';' и BOM — совместимо со старыми конфигурациями 1С."""
    prepared = _prep(df)
    return prepared.to_csv(index=False, sep=";").encode("utf-8-sig")
