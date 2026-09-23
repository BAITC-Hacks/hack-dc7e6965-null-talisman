"""Live acceptance scenarios. Missing evidence is never displayed as a pass."""

from dataclasses import dataclass, field
import logging

import numpy as np
import pandas as pd

from app.backend import engine_function


class MissingEvidence(ValueError):
    pass


@dataclass
class CheckResult:
    title: str
    status: str
    message: str
    rows: list = field(default_factory=list)


def copy_data(data):
    return {name: table.copy(deep=True) for name, table in data.items()}


def select(frame, sku, warehouse=None):
    selected = frame[frame.sku.eq(sku)]
    if warehouse is not None:
        selected = selected[selected.warehouse.eq(warehouse)]
    if selected.empty:
        raise MissingEvidence(f"Нет контрольной позиции {sku}. Проверку нельзя подтвердить на этих данных.")
    return selected.iloc[0]


def comparison(label, before, after, passed):
    return {"Сценарий": label, "До": float(before), "После": float(after), "Результат": "✅" if passed else "❌"}


def sources(data, params, recommend):
    base = recommend(copy_data(data), dict(params))
    if base.empty:
        raise MissingEvidence("Пустой результат расчёта.")
    row = base.iloc[0]
    identity = (row.sku, row.warehouse)
    rows = []

    def compare(label, changed, settings=params, target=identity):
        before = select(base, *target).need_raw
        after = select(recommend(changed, dict(settings)), *target).need_raw
        rows.append(comparison(label, before, after, not np.isclose(before, after)))

    changed = copy_data(data)
    transit = changed.get("in_transit", pd.DataFrame(columns=["sku", "warehouse", "qty", "eta"]))
    changed["in_transit"] = pd.concat([transit, pd.DataFrame([dict(sku=row.sku, warehouse=row.warehouse, qty=500, eta=params["today"])])], ignore_index=True)
    compare("В пути +500 шт. → потребность", changed)

    nonzero = base[base.on_hand > 0]
    if nonzero.empty:
        raise MissingEvidence("Для проверки остатков нужен товар с положительным остатком.")
    stockrow = nonzero.iloc[0]
    changed = copy_data(data)
    mask = changed["stock"].sku.eq(stockrow.sku) & changed["stock"].warehouse.eq(stockrow.warehouse)
    changed["stock"].loc[mask, "on_hand"] = changed["stock"].loc[mask, "on_hand"].astype(float) * .5
    compare("Остаток −50% → потребность", changed, target=(stockrow.sku, stockrow.warehouse))

    settings = dict(params, growth_override={**params.get("growth_override", {}), row.category: float(row.growth_pct) + 20})
    compare("Плановый прирост +20 п.п. → потребность", copy_data(data), settings)

    alternatives = data["products"].category.dropna().unique()
    alternatives = [category for category in alternatives if category != row.category]
    if not alternatives:
        raise MissingEvidence("Для проверки категории нужны минимум две категории.")
    changed = copy_data(data)
    changed["products"].loc[changed["products"].sku.eq(row.sku), "category"] = alternatives[0]
    compare("Другая категория → потребность", changed)

    target = select(base, "DEMO-STOCKOUT")
    changed = copy_data(data)
    changed["stockouts"] = changed["stockouts"].iloc[:0].copy()
    compare("Без периодов отсутствия → потребность", changed, target=(target.sku, target.warehouse))

    bom = data.get("bom", pd.DataFrame())
    if bom.empty:
        raise MissingEvidence("Нет материальной ведомости BOM для проверки комплектов.")
    sold = set(data["sales"].sku)
    entries = bom[bom.parent_sku.isin(sold) & bom.component_sku.isin(base.sku)]
    if entries.empty:
        raise MissingEvidence("Нет продаж комплектов с компонентами в результате расчёта.")
    target = select(base, entries.iloc[0].component_sku)
    changed = copy_data(data)
    changed["sales"] = changed["sales"][~changed["sales"].sku.isin(bom.parent_sku)].copy()
    compare("Без продаж комплектов → потребность компонента", changed, target=(target.sku, target.warehouse))
    return rows


def seasonal(data, params, recommend):
    base = select(recommend(copy_data(data), dict(params)), "DEMO-SEASON")
    series = engine_function("engine.pipeline", "sku_series")(copy_data(data), base.sku, base.warehouse)
    predictions = series.loc[series.forecast.notna(), ["month", "forecast"]].copy()
    predictions["month"] = pd.to_datetime(predictions.month.astype(str))
    if predictions.month.dt.month.nunique() < 12:
        raise MissingEvidence("Для отношения пика к минимуму нужен прогноз полного годового цикла (12 месяцев) в sku_series.")
    values = predictions.forecast.astype(float)
    if not np.isfinite(values).all() or (values < 0).any() or values.max() <= 0:
        raise MissingEvidence("Сезонный прогноз содержит некорректные или нулевые значения.")
    ratio = values.max() / values.min() if values.min() > 0 else float("inf")
    rows = [comparison("Пик / минимум > 1.5", 1.5, ratio, ratio > 1.5)]

    # Three rolling holdouts. Never expose held-out sales or stockout periods to the model.
    actual_sales = data["sales"].copy()
    actual_sales["date"] = pd.to_datetime(actual_sales.date)
    last = pd.Timestamp(params["today"]).to_period("M") - 1
    errors, naive_errors, actuals = [], [], []
    for month in pd.period_range(last - 2, last, freq="M"):
        start, end = month.start_time, (month + 1).start_time
        changed = copy_data(data)
        changed["sales"] = actual_sales[actual_sales.date < start].copy()
        outages = changed.get("stockouts", pd.DataFrame())
        if not outages.empty:
            outages = outages[pd.to_datetime(outages.start) < start].copy()
            outages["end"] = pd.to_datetime(outages.end).clip(upper=start - pd.Timedelta(days=1))
            changed["stockouts"] = outages
        changed["suppliers"]["lead_time_days"] = 0
        settings = dict(params, today=start.date().isoformat(), review_days=month.days_in_month,
                        growth_override={category: 0 for category in data["products"].category.unique()})
        predicted = float(select(recommend(changed, settings), base.sku, base.warehouse).forecast_horizon)
        relevant = actual_sales[actual_sales.sku.eq(base.sku) & actual_sales.warehouse.eq(base.warehouse)]
        observed = float(relevant.loc[(relevant.date >= start) & (relevant.date < end), "qty"].sum())
        history = relevant[relevant.date < start].groupby(relevant.date.dt.to_period("M")).qty.sum()
        if history.empty:
            raise MissingEvidence("Недостаточно истории для проверки на отложенных месяцах.")
        history = history.reindex(pd.period_range(history.index.min(), month - 1, freq="M"), fill_value=0)
        naive = float(history.mean())
        actuals.append(abs(observed))
        errors.append(abs(predicted - observed))
        naive_errors.append(abs(naive - observed))
        rows.append(comparison(f"{month}: факт → прогноз", observed, predicted, np.isfinite(predicted)))
    if sum(actuals) <= 0:
        raise MissingEvidence("Нет продаж в отложенных месяцах для расчёта WAPE.")
    model_wape = sum(errors) / sum(actuals) * 100
    naive_wape = sum(naive_errors) / sum(actuals) * 100
    rows.append(comparison("WAPE: среднее → модель, % (меньше — лучше)", naive_wape, model_wape, model_wape < naive_wape))
    return rows


def stockouts(data, params, recommend):
    with_outages = select(recommend(copy_data(data), dict(params)), "DEMO-STOCKOUT")
    changed = copy_data(data)
    changed["stockouts"] = changed["stockouts"].iloc[:0].copy()
    without = select(recommend(changed, dict(params)), with_outages.sku, with_outages.warehouse)
    return [comparison("Потребность без восстановления → с восстановлением", without.need_raw, with_outages.need_raw,
                       with_outages.need_raw > without.need_raw)]


def oneoff(data, params, recommend):
    base = select(recommend(copy_data(data), dict(params)), "DEMO-ONEOFF")
    changed = copy_data(data)
    sales = changed["sales"]
    matching = sales[sales.sku.eq(base.sku) & sales.warehouse.eq(base.warehouse) & (sales.qty > 0)]
    if matching.empty:
        raise MissingEvidence("Нет обычных продаж DEMO-ONEOFF для сравнения.")
    extra = matching.iloc[-1].copy()
    # Add a genuinely new customer to an existing historical date.
    extra["client_id"] = "ui-check-oneoff-new-customer"
    while extra["client_id"] in set(sales.client_id):
        extra["client_id"] += "-new"
    extra["qty"] = float(matching.qty.median()) * 50
    changed["sales"] = pd.concat([sales, extra.to_frame().T], ignore_index=True)
    after = select(recommend(changed, dict(params)), base.sku, base.warehouse)
    return [comparison("К заказу после разовой продажи 50× медианы (рост ≤10%)", base.recommended_qty,
                       after.recommended_qty, after.recommended_qty <= base.recommended_qty * 1.1)]


def grouping(data, params, recommend):
    result = recommend(copy_data(data), dict(params))
    if result.empty:
        raise MissingEvidence("Нет рекомендаций для проверки группировки.")
    explanations = result.explanation.notna() & result.explanation.astype(str).str.strip().ne("")
    grouped = result.groupby("supplier_id").recommended_qty.sum()
    covered = result.groupby("supplier_id").size().sum()
    return [comparison("Строк с обоснованием", len(result), explanations.sum(), explanations.all()),
            comparison("Строк после группировки", len(result), covered, covered == len(result)),
            comparison("Сумма количества по поставщикам", result.recommended_qty.sum(), grouped.sum(),
                       np.isclose(result.recommended_qty.sum(), grouped.sum()))]


SCENARIOS = [
    ("1. Все источники влияют на заказ", sources),
    ("2. Сезонность и качество прогноза", seasonal),
    ("3. Восстановление упущенного спроса", stockouts),
    ("4. Защита от разового крупного заказа", oneoff),
    ("5. Поставщики и обоснования", grouping),
]


def run_checks(data, params, progress=None):
    recommend = engine_function("engine.pipeline", "recommend")
    results = []
    # Evaluate all reference SKUs regardless of the main page's display filters.
    settings = dict(params, warehouse=None, category=None)
    for index, (title, scenario) in enumerate(SCENARIOS):
        try:
            rows = scenario(copy_data(data), dict(settings), recommend)
            passed = all(row["Результат"] == "✅" for row in rows)
            results.append(CheckResult(title, "passed" if passed else "failed",
                                       "Критерий выполнен." if passed else "Критерий не выполнен — требуется проверка ядра или данных.", rows))
        except MissingEvidence as exc:
            results.append(CheckResult(title, "unavailable", str(exc)))
        except Exception:
            logging.getLogger(__name__).exception("Acceptance scenario failed: %s", title)
            results.append(CheckResult(title, "error", "Сценарий не удалось выполнить. Проверьте контракт ядра и входные данные."))
        if progress:
            progress((index + 1) / len(SCENARIOS))
    return results
