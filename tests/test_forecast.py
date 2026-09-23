"""Юнит-тесты engine/forecast.py на маленьких синтетических рядах — без
обращения к data/generate.py, каждый тест сам строит нужный ряд.
docs/PLAN-2.md, задача 1 (Абдуали)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.forecast import (
    _blend_season_index,
    _theil_sen_pct_per_month,
    forecast_sku,
)

NEUTRAL_SEASON = {m: 1.0 for m in range(1, 13)}


def _series(months: pd.PeriodIndex, values, availability=1.0) -> pd.DataFrame:
    """Собирает DataFrame в формате demand.monthly_clean_series для одного sku."""
    values = list(values)
    return pd.DataFrame({
        "month": months, "clean": values, "actual": values,
        "availability_frac": availability,
    })


# ---------------------------------------------------------------- Theil-Sen

def test_theil_sen_detects_consistent_growth():
    """Устойчивый рост во всех половинах окна распознаётся и близок к заданному."""
    y = pd.Series([100 * 1.04**i for i in range(12)])
    trend = _theil_sen_pct_per_month(y)
    assert 2.0 < trend < 6.0  # ~4%/мес с запасом на метод медианы попарных наклонов


def test_theil_sen_ignores_single_reversal():
    """Наклон разного знака в двух половинах окна -> тренд не признаётся (0.0),
    а не выводится как средний между спадом и ростом."""
    first_half = [200, 180, 160, 140, 120, 100]   # спад
    second_half = [100, 120, 140, 160, 180, 200]  # рост
    y = pd.Series(first_half + second_half)
    assert _theil_sen_pct_per_month(y) == 0.0


def test_theil_sen_ignores_noise_below_threshold():
    """Наклон меньше TREND_MIN_PCT (1%/мес) считается шумом, не трендом."""
    y = pd.Series([100.0] * 11 + [100.3])  # почти плоский ряд
    assert _theil_sen_pct_per_month(y) == 0.0


def test_theil_sen_clips_extreme_trend():
    y = pd.Series([100 * 1.5**i for i in range(12)])  # +50%/мес, заведомо за клипом
    assert _theil_sen_pct_per_month(y) == pytest.approx(10.0)  # TREND_CLIP верх


# ------------------------------------------------------------- intermittent

def test_intermittent_flagged_for_mostly_zero_series():
    months = pd.period_range("2023-01", periods=14, freq="M")
    values = [0] * 8 + [10, 0, 15, 0, 12, 0]  # > 50% нулевых месяцев
    series = _series(months, values)
    model = forecast_sku(series, NEUTRAL_SEASON, growth_pct=0.0)
    assert model["flags"] == ["intermittent"]
    assert model["season_index"] == NEUTRAL_SEASON
    assert model["level"] > 0


def test_regular_series_is_not_intermittent():
    months = pd.period_range("2023-01", periods=14, freq="M")
    values = [50 + i for i in range(14)]  # каждый месяц с продажами
    series = _series(months, values)
    model = forecast_sku(series, NEUTRAL_SEASON, growth_pct=0.0)
    assert "intermittent" not in model["flags"]


# ---------------------------------------------------------------------- new

def test_new_sku_has_low_confidence():
    months = pd.period_range("2026-07", periods=2, freq="M")
    series = _series(months, [10, 14])
    model = forecast_sku(series, NEUTRAL_SEASON, growth_pct=0.0)
    assert model["flags"] == ["new"]
    assert model["confidence"] == "low"
    assert model["wape_model"] is None and model["wape_naive"] is None


def test_empty_series_is_also_new_with_low_confidence():
    model = forecast_sku(pd.DataFrame(columns=["month", "clean", "actual", "availability_frac"]),
                          NEUTRAL_SEASON, growth_pct=0.0)
    assert model["flags"] == ["new"]
    assert model["confidence"] == "low"
    assert model["level"] == 0.0


# ---------------------------------------------------------- WAPE / backtest

def test_wape_model_beats_naive_on_clean_seasonal_pattern():
    """Ряд построен ТОЧНО по заданной сезонности без шума и без тренда: модель
    обязана предсказать отложенные месяцы почти без ошибки (WAPE ~= 0), а
    наивное среднее — не идеально, т.к. усредняет разные по сезону месяцы."""
    category_index = {1: 1.5, 2: 1.5, 3: 0.5, 4: 0.5, 5: 1.0, 6: 1.0,
                       7: 1.5, 8: 1.5, 9: 0.5, 10: 0.5, 11: 1.0, 12: 1.0}
    assert np.mean(list(category_index.values())) == pytest.approx(1.0)
    level0 = 100.0
    months = pd.period_range("2024-01", periods=15, freq="M")
    values = [level0 * category_index[m.month] for m in months]
    series = _series(months, values)

    model = forecast_sku(series, category_index, growth_pct=0.0)

    assert model["wape_model"] is not None
    assert model["wape_model"] == pytest.approx(0.0, abs=1e-9)
    assert model["wape_naive"] > model["wape_model"]
    assert model["confidence"] == "medium"  # backtest подтвердил модель, но < SHORT_HISTORY_MONTHS


def test_wape_none_when_history_too_short_for_backtest():
    months = pd.period_range("2026-01", periods=6, freq="M")
    series = _series(months, [10, 12, 11, 13, 12, 14])
    model = forecast_sku(series, NEUTRAL_SEASON, growth_pct=0.0)
    assert model["wape_model"] is None
    assert model["wape_naive"] is None


def test_backtest_train_season_index_ignores_held_out_months():
    """Утечка будущего: сезонность для backtest должна зависеть только от train
    (первые n-3 месяца). Меняем ТОЛЬКО отложенные 3 месяца и убеждаемся, что
    train-сезонность (и, значит, предсказание backtest) не меняется вообще."""
    months = pd.period_range("2022-01", periods=20, freq="M")
    base = [100 + 40 * np.sin(2 * np.pi * (m.month - 1) / 12) for m in months]
    s1 = pd.Series(base, index=months)
    s2 = s1.copy()
    s2.iloc[-3:] = [1e6, 1.0, 5e5]  # ломаем только hold, train нетронут

    idx1, short1 = _blend_season_index(s1.iloc[:-3], NEUTRAL_SEASON)
    idx2, short2 = _blend_season_index(s2.iloc[:-3], NEUTRAL_SEASON)
    assert idx1 == idx2
    assert short1 == short2

    # На уровне forecast_sku: WAPE неизбежно отличается (факт в hold другой),
    # но модель не должна падать и не должна "подстроиться" под аномалию —
    # её собственный прогноз использует только train-сезонность/тренд.
    series1 = pd.DataFrame({"month": months, "clean": s1.values, "actual": s1.values, "availability_frac": 1.0})
    series2 = pd.DataFrame({"month": months, "clean": s2.values, "actual": s2.values, "availability_frac": 1.0})
    model1 = forecast_sku(series1, NEUTRAL_SEASON, growth_pct=0.0)
    model2 = forecast_sku(series2, NEUTRAL_SEASON, growth_pct=0.0)
    assert model1["wape_model"] is not None and model2["wape_model"] is not None
    # Аномальный hold в s2 обязан ухудшить (не улучшить) точность модели —
    # если бы сезонность утекала из hold, модель могла бы "подогнаться" и
    # получить подозрительно маленький WAPE несмотря на аномалию.
    assert model2["wape_model"] > model1["wape_model"]


def test_confidence_drops_to_low_when_backtest_underperforms_naive():
    """Уверенный рост в train (9 мес.), который резко обрывается в отложенных
    3 месяцах: модель экстраполирует тренд и переоценивает сильнее, чем плоское
    наивное среднее — confidence обязан упасть до low."""
    months = pd.period_range("2023-01", periods=12, freq="M")
    train_vals = [50 * 1.15**i for i in range(9)]
    hold_vals = [10.0, 8.0, 12.0]
    series = _series(months, train_vals + hold_vals)
    model = forecast_sku(series, NEUTRAL_SEASON, growth_pct=0.0)
    assert model["wape_model"] > model["wape_naive"] * 1.1
    assert model["confidence"] == "low"
