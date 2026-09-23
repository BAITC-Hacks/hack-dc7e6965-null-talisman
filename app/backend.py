"""Only integration point with the team's engine; no forecasting logic here."""

import importlib
import io
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
TABLES = ("sales", "stock", "in_transit", "stockouts", "products", "suppliers", "growth", "bom")


class BackendUnavailable(ValueError):
    pass


def engine_function(module: str, name: str):
    try:
        return getattr(importlib.import_module(module), name)
    except (ImportError, AttributeError) as exc:
        raise BackendUnavailable(
            f"Расчётный модуль ещё не подключён ({module}.{name}). "
            "Интерфейс готов к подключению; обновите код команды и повторите расчёт."
        ) from exc


def demo_files() -> tuple:
    directory = ROOT / "data" / "demo"
    if not (directory / "sales.csv").exists():
        if not (ROOT / "data" / "generate.py").exists():
            raise BackendUnavailable("Демонстрационные данные ещё не добавлены командой. Можно загрузить свои файлы.")
        try:
            subprocess.run([sys.executable, "-m", "data.generate"], cwd=ROOT,
                           check=True, capture_output=True, timeout=60)
        except (subprocess.SubprocessError, OSError) as exc:
            raise ValueError("Не удалось создать демоданные. Проверьте запуск python -m data.generate.") from exc
    return tuple((path.name, path.read_bytes()) for path in sorted(directory.glob("*.csv")))


@st.cache_data(show_spinner=False, max_entries=4)
def load_files(files: tuple, today=None):
    """CSV/XLSX uploads are normalized to CSV for the engine's directory loader."""
    names = set()
    if not files:
        raise ValueError("Загрузите входные таблицы CSV или XLSX.")
    for filename, _ in files:
        stem = Path(filename).stem
        if stem not in TABLES:
            raise ValueError(f"Неизвестная таблица {filename}. Допустимы: {', '.join(TABLES)}.")
        if stem in names:
            raise ValueError(f"Таблица {stem} загружена дважды. Оставьте один файл.")
        names.add(stem)
    missing = {"sales", "stock", "products", "suppliers"} - names
    if missing:
        raise ValueError("Не хватает файлов: " + ", ".join(sorted(missing)))
    loader = engine_function("engine.io", "load_data")
    with tempfile.TemporaryDirectory(prefix="null-talisman-input-") as directory:
        for filename, content in files:
            target = Path(directory) / f"{Path(filename).stem}.csv"
            if Path(filename).suffix.lower() == ".xlsx":
                table = pd.read_excel(io.BytesIO(content), dtype={"sku": str, "supplier_id": str, "client_id": str})
                table.to_csv(target, index=False)
            else:
                target.write_bytes(content)
        loaded = loader(Path(directory), today=today) if today is not None else loader(Path(directory))
    # The planned loader may expose warnings alongside the dictionary.
    data, warnings = loaded if isinstance(loaded, tuple) and len(loaded) == 2 else (loaded, [])
    if not isinstance(data, dict):
        raise ValueError("Загрузчик должен вернуть словарь таблиц (или словарь и список предупреждений).")
    for name, columns in {"stock": {"warehouse"}, "products": {"category"}}.items():
        if name not in data or not isinstance(data[name], pd.DataFrame) or not columns.issubset(data[name]):
            raise ValueError(f"Загрузчик вернул некорректную таблицу {name}.")
    if "growth" in data and not data["growth"].empty and not {"category", "growth_pct"}.issubset(data["growth"]):
        raise ValueError("В growth необходимы category и growth_pct.")
    return data, warnings or []


def validate_result(frame):
    required = {"supplier_id", "supplier_name", "sku", "name", "category", "warehouse",
                "on_hand", "in_transit", "forecast_horizon", "recommended_qty", "urgency", "confidence", "explanation"}
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("Расчёт не вернул таблицу. Проверьте интеграцию с ядром.")
    missing = required - set(frame.columns)
    if missing:
        raise ValueError("В результате отсутствуют колонки: " + ", ".join(sorted(missing)))
    if frame.empty:
        return frame
    frame = frame.copy()
    for column in ("supplier_id", "supplier_name", "sku", "name", "warehouse", "explanation"):
        if frame[column].isna().any() or frame[column].astype(str).str.strip().eq("").any():
            raise ValueError(f"В результате есть пустое поле {column}.")
    if frame.duplicated(["supplier_id", "sku", "warehouse"]).any():
        raise ValueError("В расчёте повторяется позиция одного склада и поставщика.")
    for column in ("on_hand", "in_transit", "forecast_horizon", "recommended_qty"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if not np.isfinite(frame[column]).all() or (frame[column] < 0).any():
            raise ValueError(f"Некорректные значения в колонке {column}.")
    if (frame["recommended_qty"] % 1 != 0).any():
        raise ValueError("Рекомендованное количество должно быть целым.")
    frame["recommended_qty"] = frame["recommended_qty"].astype("int64")
    return frame.reset_index(drop=True)


@st.cache_data(show_spinner=False, max_entries=8)
def calculate(data, params):
    return validate_result(engine_function("engine.pipeline", "recommend")(data, params))


@st.cache_data(show_spinner=False, max_entries=32)
def series(data, sku, warehouse, today=None, growth_pct=0.0, forward_months=6):
    result = engine_function("engine.pipeline", "sku_series")(
        data, sku, warehouse, today=today, growth_pct=growth_pct, forward_months=forward_months
    )
    if not isinstance(result, pd.DataFrame) or not {"month", "raw", "clean", "forecast"}.issubset(result):
        raise ValueError("Для графика нужны month, raw, clean, forecast из sku_series.")
    return result
