"""Approval snapshots and downloads. No supplier communication is performed."""

import hashlib
import io
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

ORDER_DIR = Path(__file__).resolve().parents[1] / "data" / "orders"
EXPORT_COLUMNS = {
    "sku": "Артикул", "name": "Номенклатура", "warehouse": "Склад",
    "recommended_qty": "Количество", "unit": "Ед.",
    "supplier_name": "Поставщик", "urgency": "Срочность", "explanation": "Обоснование",
}


def fingerprint(frame: pd.DataFrame) -> str:
    """Invalidate an approval when any exported value or quantity changes."""
    normalized = frame.sort_values(["supplier_id", "sku", "warehouse"])
    return hashlib.sha256(normalized.to_json(orient="records", date_format="iso").encode()).hexdigest()


def edited_order(original: pd.DataFrame, edited: pd.DataFrame) -> pd.DataFrame:
    result = original.copy()
    if len(result) != len(edited):
        raise ValueError("Состав заказа изменился. Повторите расчёт.")
    quantities = pd.to_numeric(edited["recommended_qty"], errors="coerce")
    if not quantities.map(lambda x: pd.notna(x) and math.isfinite(x) and 0 <= x <= 1e9 and float(x).is_integer()).all():
        raise ValueError("Количество должно быть целым числом от 0 до 1 000 000 000.")
    result["original_qty"] = original["recommended_qty"].to_numpy()
    result["recommended_qty"] = quantities.astype("int64").to_numpy()
    result["manually_changed"] = result["recommended_qty"] != result["original_qty"]
    return result


def approve(frame: pd.DataFrame, author: str, params: dict, directory: Path = ORDER_DIR) -> dict:
    if not author.strip():
        raise ValueError("Укажите имя ответственного за утверждение.")
    if frame["supplier_id"].nunique() != 1:
        raise ValueError("Утверждайте каждый заказ поставщику отдельно.")
    # Revalidate at the persistence boundary, even if the UI already validated.
    edited_order(frame, frame)
    if not (frame["recommended_qty"] > 0).any():
        raise ValueError("В заказе нет позиций с положительным количеством.")
    now = datetime.now(timezone.utc)
    supplier = str(frame.iloc[0]["supplier_id"])
    safe_supplier = re.sub(r"[^\w-]", "_", supplier)[:60] or "supplier"
    order_id = f"{now:%Y%m%dT%H%M%S%f}_{safe_supplier}_{uuid4().hex[:8]}"
    payload = {
        "id": order_id, "status": "approved", "author": author.strip(),
        "approved_at": now.isoformat(), "supplier_id": supplier,
        "params": params, "fingerprint": fingerprint(frame),
        "items": json.loads(frame.to_json(orient="records", date_format="iso")),
    }
    directory.mkdir(parents=True, exist_ok=True)
    # Unique append-only files preserve earlier approvals and prevent overwrites.
    path = directory / f"{order_id}.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
    return payload


def export_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.loc[frame["recommended_qty"] > 0].copy()
    result["unit"] = result.get("unit", "шт.")
    if "manually_changed" in result:
        for index in result.index[result["manually_changed"]]:
            result.loc[index, "explanation"] = (
                f"{result.loc[index, 'explanation']} Изменено вручную: "
                f"{result.loc[index, 'original_qty']:g} → {result.loc[index, 'recommended_qty']:g}."
            )
    result = result[list(EXPORT_COLUMNS)].rename(columns=EXPORT_COLUMNS)
    # Spreadsheet formula injection protection for names and explanations from uploads.
    for col in result.select_dtypes(include=["object", "string"]):
        result[col] = result[col].map(
            lambda value: "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value
        )
    return result


def csv_bytes(frame: pd.DataFrame) -> bytes:
    return export_frame(frame).to_csv(index=False, sep=";").encode("utf-8-sig")


def xlsx_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for number, (_, group) in enumerate(frame.groupby("supplier_id", sort=False), start=1):
            title = re.sub(r"[\\/*?:\[\]]", "_", str(group.iloc[0]["supplier_name"]))
            sheet = f"{number}_{title}"[:31]
            export_frame(group).to_excel(writer, sheet_name=sheet, index=False)
            worksheet = writer.sheets[sheet]
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for column, width in zip("ABCDEFGH", [22, 40, 20, 15, 10, 30, 18, 90]):
                worksheet.column_dimensions[column].width = width
    return buffer.getvalue()
