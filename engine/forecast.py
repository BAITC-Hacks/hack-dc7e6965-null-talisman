"""Прогноз спроса: сезонность, устойчивый тренд, прирост от менеджера.
Алгоритм — docs/PLAN.md, раздел 4, шаг 4.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine.demand import STOCKOUT_MIN_AVAILABILITY

SEASON_MIN, SEASON_MAX = 0.3, 3.0
SHORT_HISTORY_MONTHS = 24  # меньше -> используем сезонность категории
TREND_WINDOW_MONTHS = 12
TREND_MIN_PCT = 1.0  # %/мес, ниже считаем шумом
TREND_CLIP = (-5.0, 10.0)
INTERMITTENT_ZERO_FRAC = 0.5
NEW_SKU_MIN_MONTHS = 3
LEVEL_WINDOW_MONTHS = 6
BACKTEST_MONTHS = 3


def _centered_rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    """То же самое, что pandas .rolling(window, center=True).mean(), но на чистом
    numpy через префиксные суммы — без построения pandas Series/Index на каждый
    вызов. Проверено на совпадение с pandas поэлементно (см. коммит):
    для чётного окна pandas берёт [i - window//2, i + window//2 - 1]."""
    n = len(values)
    result = np.full(n, np.nan)
    left = window // 2
    right = window // 2 - 1
    if n < window:
        return result
    csum_padded = np.concatenate(([0.0], np.cumsum(values)))
    idx = np.arange(left, n - right)
    sums = csum_padded[idx + right + 1] - csum_padded[idx - left]
    result[idx] = sums / window
    return result


def _seasonal_ratio_to_cma(series: pd.Series) -> dict[int, float]:
    """series индексирован последовательными помесячными Period. Возвращает
    {месяц_года(1-12): фактор}, среднее = 1, клип [SEASON_MIN, SEASON_MAX].

    forecast_sku() вызывает эту функцию дважды на каждый sku (полный ряд +
    train-часть для честного backtest), поэтому на ~300 sku набегает под 1000
    вызовов на маленьких (≤36 элементов) рядах — конструирование pandas Series
    на каждый вызов само по себе занимало заметную долю времени recommend().
    Здесь всё считается на чистых numpy-массивах, pandas-индекс месяца
    вычисляется один раз."""
    if len(series) < 13:
        return {m: 1.0 for m in range(1, 13)}
    months = series.index.month.to_numpy()
    values = series.to_numpy(dtype=float)
    cma = _centered_rolling_mean(values, 12)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = values / cma
    ratio[~np.isfinite(ratio)] = np.nan

    by_month = np.ones(13)
    for m in range(1, 13):
        vals = ratio[months == m]
        vals = vals[~np.isnan(vals)]
        if len(vals):
            by_month[m] = vals.mean()
    mean_factor = by_month[1:].mean() or 1.0
    return {m: float(np.clip(by_month[m] / mean_factor, SEASON_MIN, SEASON_MAX)) for m in range(1, 13)}


def build_category_seasonal(monthly_clean: pd.DataFrame, products: pd.DataFrame) -> dict[str, dict[int, float]]:
    """Сезонность категории — по объединённому (просуммированному) ряду всех sku категории."""
    if monthly_clean.empty:
        return {}
    merged = monthly_clean.merge(products[["sku", "category"]], on="sku", how="left")
    out = {}
    for category, grp in merged.groupby("category"):
        pooled = grp.groupby("month")["clean"].sum().sort_index()
        out[category] = _seasonal_ratio_to_cma(pooled)
    return out


def _theil_sen_pct_per_month(deseason: pd.Series) -> float:
    """Медиана попарных наклонов на последнем окне, в %/мес от среднего уровня.
    0.0, если знак наклона не устойчив (разный в двух половинах окна) или мал."""
    window = deseason.tail(TREND_WINDOW_MONTHS)
    n = len(window)
    if n < 6:
        return 0.0
    y = window.values
    x = np.arange(n)
    slopes = []
    for i in range(n):
        for j in range(i + 1, n):
            if x[j] != x[i]:
                slopes.append((y[j] - y[i]) / (x[j] - x[i]))
    if not slopes:
        return 0.0
    slope = float(np.median(slopes))
    level = float(np.mean(y)) or 1.0
    pct_per_month = 100 * slope / level

    half = n // 2
    slope_1 = float(np.median([(y[b] - y[a]) / (b - a) for a in range(half) for b in range(a + 1, half) if b != a])) if half >= 2 else 0.0
    slope_2 = float(np.median([(y[b] - y[a]) / (b - a) for a in range(half, n) for b in range(a + 1, n) if b != a])) if (n - half) >= 2 else 0.0
    consistent = (slope_1 >= 0 and slope_2 >= 0) or (slope_1 <= 0 and slope_2 <= 0)

    if not consistent or abs(pct_per_month) < TREND_MIN_PCT:
        return 0.0
    return float(np.clip(pct_per_month, *TREND_CLIP))


def _sigma_month(s: pd.Series, avail: pd.Series, window: int = 12) -> float:
    """Стандартное отклонение спроса для страхового запаса. Месяцы с сорванной
    доступностью товара (stockout) — это провал предложения, а не спроса, и не
    компенсированные (availability_frac уже занижен, только когда stockout НЕ
    отражён в данных) такие месяцы раздувают дисперсию мимо реальной волатильности
    спроса. Поэтому считаем sigma по «нормальным» месяцам, если их хватает."""
    recent = s.tail(window)
    if len(recent) < 2:
        return float(recent.mean() * 0.5) if len(recent) else 0.0
    recent_avail = avail.reindex(recent.index).fillna(1.0)
    normal = recent[recent_avail >= STOCKOUT_MIN_AVAILABILITY]
    source = normal if len(normal) >= 6 else recent
    return float(source.std(ddof=0)) if len(source) > 1 else float(recent.mean() * 0.5)


def _blend_season_index(s: pd.Series, category_index: dict[int, float]) -> tuple[dict[int, float], bool]:
    """Сезонность sku, смешанная с сезонностью категории по длине истории.
    Возвращает (season_index, short_history). Вынесено отдельно, чтобы backtest
    мог честно пересчитать сезонность только по train-части ряда — иначе
    season_index, посчитанный по полному ряду, «подглядывает» в отложенные
    для backtest месяцы и WAPE модели становится оптимистичнее реального."""
    n = len(s)
    if n >= SHORT_HISTORY_MONTHS:
        sku_index = _seasonal_ratio_to_cma(s)
        years = n / 12.0
        w = min(1.0, years / 3.0)
        blended = {m: w * sku_index.get(m, 1.0) + (1 - w) * category_index.get(m, 1.0) for m in range(1, 13)}
        mean_f = np.mean(list(blended.values())) or 1.0
        return {m: float(np.clip(v / mean_f, SEASON_MIN, SEASON_MAX)) for m, v in blended.items()}, False
    return (category_index or {m: 1.0 for m in range(1, 13)}), True


def _wape(actual: np.ndarray, forecast: np.ndarray) -> float:
    denom = np.sum(np.abs(actual))
    if denom <= 0:
        return 0.0
    return float(np.sum(np.abs(actual - forecast)) / denom)


def forecast_sku(series: pd.DataFrame, category_index: dict[int, float], growth_pct: float) -> dict:
    """series: колонки month(Period), clean, actual, отсортировано по month, только
    для одной пары (sku, warehouse). Возвращает параметры модели + confidence."""
    if series.empty:
        return {
            "level": 0.0, "sigma_month": 0.0, "trend_pct_month": 0.0,
            "season_index": category_index or {m: 1.0 for m in range(1, 13)},
            "confidence": "low", "flags": ["new"], "wape_model": None, "wape_naive": None,
        }

    sorted_series = series.sort_values("month").set_index("month")
    s = sorted_series["clean"]
    avail = sorted_series.get("availability_frac", pd.Series(1.0, index=s.index))
    n_months = len(s)
    zero_frac = float((series["actual"] == 0).mean())
    flags = []

    if n_months < NEW_SKU_MIN_MONTHS:
        level = float(s.mean()) if n_months else 0.0
        return {
            "level": level, "sigma_month": _sigma_month(s, avail) if n_months > 1 else level * 0.5,
            "trend_pct_month": 0.0, "season_index": category_index or {m: 1.0 for m in range(1, 13)},
            "confidence": "low", "flags": ["new"], "wape_model": None, "wape_naive": None,
        }

    if zero_frac > INTERMITTENT_ZERO_FRAC:
        nonzero = s[s > 0]
        level = float(nonzero.mean() * (1 - zero_frac)) if len(nonzero) else 0.0
        return {
            "level": level, "sigma_month": _sigma_month(s, avail),
            "trend_pct_month": 0.0, "season_index": {m: 1.0 for m in range(1, 13)},
            "confidence": "medium" if n_months >= 12 else "low",
            "flags": ["intermittent"], "wape_model": None, "wape_naive": None,
        }

    season_index, short_history = _blend_season_index(s, category_index)
    if short_history:
        flags.append("short_history")

    deseason = s / s.index.map(lambda p: season_index.get(p.month, 1.0))
    level = float(deseason.tail(LEVEL_WINDOW_MONTHS).mean())
    trend_pct_month = _theil_sen_pct_per_month(deseason)
    sigma_month = _sigma_month(s, avail) if n_months >= 2 else level * 0.5

    wape_model = wape_naive = None
    confidence = "medium"
    if n_months >= SHORT_HISTORY_MONTHS:
        confidence = "high"
    if n_months > BACKTEST_MONTHS + 6:
        train, hold = s.iloc[:-BACKTEST_MONTHS], s.iloc[-BACKTEST_MONTHS:]
        # Сезонность для backtest считаем заново по train — иначе season_index
        # выше (посчитанный по всему ряду) утекает в предсказание отложенных
        # месяцев, и WAPE модели перестаёт быть честной оценкой "как модель
        # предсказала бы без будущего".
        train_season_index, _ = _blend_season_index(train, category_index)
        train_deseason = train / train.index.map(lambda p: train_season_index.get(p.month, 1.0))
        bt_level = float(train_deseason.tail(LEVEL_WINDOW_MONTHS).mean())
        bt_trend = _theil_sen_pct_per_month(train_deseason)
        preds = []
        for h, month in enumerate(hold.index, start=1):
            preds.append(bt_level * (1 + bt_trend / 100) ** h * train_season_index.get(month.month, 1.0))
        wape_model = _wape(hold.values, np.array(preds))
        wape_naive = _wape(hold.values, np.full(len(hold), train.tail(LEVEL_WINDOW_MONTHS).mean()))
        if wape_model > wape_naive * 1.1:
            confidence = "low"

    return {
        "level": level, "sigma_month": sigma_month, "trend_pct_month": trend_pct_month,
        "season_index": season_index, "confidence": confidence, "flags": flags,
        "wape_model": wape_model, "wape_naive": wape_naive,
    }


def forecast_month_value(model: dict, months_ahead: int, month_of_year: int, growth_pct: float) -> float:
    """Прогноз спроса на конкретный будущий месяц (1 = следующий месяц)."""
    season = model["season_index"].get(month_of_year, 1.0)
    trend_mult = (1 + model["trend_pct_month"] / 100) ** months_ahead
    growth_mult = 1 + growth_pct / 100
    return max(0.0, model["level"] * trend_mult * season * growth_mult)
