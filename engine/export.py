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
    out = df.loc[df["recommended_qty"] > 0].copy()
    if "manually_changed" in out:
        for index in out.index[out["manually_changed"]]:
            out.loc[index, "explanation"] = (
                f"{out.loc[index, 'explanation']} Изменено вручную: "
                f"{out.loc[index, 'original_qty']:g} → {out.loc[index, 'recommended_qty']:g}."
            )
    out["unit"] = "шт"
    out["urgency"] = out["urgency"].map(URGENCY_LABELS).fillna(out["urgency"])
    out = out[list(EXPORT_COLUMNS.keys())].rename(columns=EXPORT_COLUMNS)
    for col in out.select_dtypes(include=["object", "string"]):
        out[col] = out[col].map(
            lambda value: "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value
        )
    return out


def _sheet_name(name: str, used: set[str]) -> str:
    safe = re.sub(r"[\[\]\:\*\?/\\]", " ", str(name)).strip()[:31] or "Поставщик"
    candidate = safe
    i = 2
    while candidate.casefold() in used:
        candidate = f"{safe[:28]}_{i}"
        i += 1
    used.add(candidate.casefold())
    return candidate


def export_xlsx(df: pd.DataFrame) -> bytes:
    """Один лист на поставщика. Возвращает содержимое файла (bytes)."""
    buf = io.BytesIO()
    used_names: set[str] = set()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        ordered = df.loc[df["recommended_qty"] > 0]
        if ordered.empty:
            _prep(df).to_excel(writer, sheet_name="Заказ", index=False)
        else:
            # IDs distinguish suppliers that happen to have the same display name.
            for _, grp in ordered.groupby("supplier_id", sort=False):
                name = _sheet_name(grp.iloc[0]["supplier_name"], used_names)
                _prep(grp).to_excel(writer, sheet_name=name, index=False)
                worksheet = writer.sheets[name]
                worksheet.freeze_panes = "A2"
                worksheet.auto_filter.ref = worksheet.dimensions
                for column, width in zip("ABCDEFGH", [22, 40, 20, 15, 10, 30, 18, 90]):
                    worksheet.column_dimensions[column].width = width
    return buf.getvalue()


def export_csv(df: pd.DataFrame) -> bytes:
    """CSV с ';' и BOM — совместимо со старыми конфигурациями 1С."""
    prepared = _prep(df)
    return prepared.to_csv(index=False, sep=";").encode("utf-8-sig")
