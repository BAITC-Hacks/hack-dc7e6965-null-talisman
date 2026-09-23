# TDD evidence: Nikita first checkpoint

## Source and user journey

Source: [`docs/PLAN.md`](../PLAN.md), sections 2, 3, 5, 6 and the 14:00 checkpoint.

As a procurement manager, I need deterministic demo data and a stable recommendation table contract so the team can build and demonstrate the supplier-order flow before the forecasting implementation is integrated.

## Task report

| Task | RED evidence | GREEN evidence | Guarantee |
|---|---|---|---|
| Recommendation contract | `pytest -q tests/test_pipeline_contract.py tests/test_generate.py` failed with `ModuleNotFoundError: engine` | Same target passed after commit `430a460` | `recommend()` returns a fresh non-empty DataFrame with the fixed 27-column UI contract |
| Deterministic generator | Initial target failed with `ModuleNotFoundError: data` | Same target passed after commit `430a460` | Seed 42 produces byte-identical copies of all eight contract CSV files |
| Reference demo scenarios | `pytest -q tests/test_generate.py` reported 2 failures: missing `DEMO-TRANSIT` and one-component BOM | Target passed after commit `1b1d7d6` | Transit, critical stock, warehouse-specific stockout and multi-component BOM fixtures are reproducible |
| Growth and short history | `pytest -q tests/test_generate.py` reported 2 failures: overdue transit ETA and missing `NEW_SKUS` | Target passed after commit `089060f` | Manual growth defaults to zero, transit ETA is future-dated and new products have under two months of history |

## Test specification

| # | What is guaranteed | Test | Type | Result |
|---|---|---|---|---|
| 1 | UI receives the exact recommendation columns in their agreed order | `test_recommend_returns_stable_ui_contract` | integration contract | PASS |
| 2 | A caller cannot mutate later recommendation results through an earlier DataFrame | `test_recommend_returns_a_fresh_dataframe` | unit | PASS |
| 3 | Same seed produces byte-identical CSV files | `test_generate_demo_data_is_deterministic` | integration | PASS |
| 4 | All eight CSV schemas and six reference SKUs exist | `test_generate_demo_data_writes_all_contract_schemas`, `test_generate_demo_data_contains_contract_and_demo_skus` | contract | PASS |
| 5 | Transit, critical stock and stockout fixtures match the demo stories | `test_reference_skus_encode_demo_scenarios` | acceptance fixture | PASS |
| 6 | Three BOM kits have at least three positive-quantity components | `test_bom_models_three_multi_component_kits` | acceptance fixture | PASS |
| 7 | Manager growth is zero by default and new SKUs have short history | `test_growth_defaults_to_zero_and_new_skus_have_short_history` | acceptance fixture | PASS |

## Verification

Commands executed from the repository root with Python 3.12 in `.venv`:

```text
python -m pytest -q --cov=engine.pipeline --cov=data.generate --cov-report=term-missing tests/test_pipeline_contract.py tests/test_generate.py
8 passed in 6.91s
TOTAL 86%

python -m data.generate --output-dir data/demo --seed 42
Generated 8 demo files in data/demo
Measured generation time: 1.17 seconds
```

Before review fixes, the four-test suite was also run three consecutive times and passed each time.

## Known gaps and merge evidence

- `recommend()` and `sku_series()` still return deliberate checkpoint placeholders. Real forecast and replenishment values are the next TDD cycle.
- `engine.pipeline` alone is below 80% line coverage; combined first-checkpoint coverage is 86%. Filter, validation and series behavior belong to the next contract cycle.
- RED checkpoints: `1d4b1e4`, `445aa80`, `403accc`.
- GREEN checkpoints: `430a460`, `1b1d7d6`, `089060f`.
