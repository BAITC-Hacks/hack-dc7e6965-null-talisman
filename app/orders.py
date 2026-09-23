"""Approval snapshots and downloads. No supplier communication is performed."""

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

ORDER_DIR = Path(__file__).resolve().parents[1] / "data" / "orders"
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



def csv_bytes(frame: pd.DataFrame) -> bytes:
    from engine.export import export_csv

    return export_csv(frame)


def xlsx_bytes(frame: pd.DataFrame) -> bytes:
    from engine.export import export_xlsx

    return export_xlsx(frame)
