# TDD evidence: Nikita first checkpoint

> Historical evidence below describes the initial isolated stub checkpoint.
> After integration with `origin/main` at `e298836`, the team's real generator
> and forecast engine replace that stub. Old commit IDs are preserved locally
> under `codex/nikita-core-pre-rebase`; they are not the rebased branch history.
> Current integration results are recorded at the end of this document.

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

## Integration with the team's implementation

The branch preserves the upstream generator, demand model and forecast model.
Generator tests now exercise `generate()` in temporary directories and verify
semantic scenarios, rather than requiring numbers from the superseded stub.
The upstream generator currently does not supply the earlier `NEW_SKUS` fixture;
the short-history guarantee above applies only to the historical checkpoint.

Regression tests caught the missing `engine.io.load_data` entrypoint used by the
UI, a mandatory date argument incompatible with the UI's `sku_series` call,
and inconsistent chart annotation fields. The integration adds the loader
entrypoint, makes the chart date optional and returns actual excluded quantities
and stockout days. Zero-order rows use the agreed `normal` urgency value.

Acceptance tests generate their own temporary CSVs, so stale local demo files
cannot change the test result. Existing local CSVs are preserved.

Windows test runs use `PYTHONUTF8=1`: an upstream UI test reads a UTF-8 approval
JSON without specifying its encoding. This avoids the Windows cp1252 default;
the application already writes approval files explicitly as UTF-8.

The real Streamlit integration test loads fresh CSVs, runs the actual loader,
recommendation function and chart function, then verifies that a recommendation
table and Plotly chart appear without a UI exception.

Remaining upstream integration limitations (not covered by a claim of full
product readiness): the chart caller does not pass the selected calculation
date/growth, and the live seasonality check requires 12 forecast months whereas
the chart API defaults to six. The live BOM check also removes kit sales after
the loader already expanded their components. These checks need a coordinated
follow-up with the UI owner; automated acceptance tests are a separate suite.

Final verification on 2026-09-23 (Python 3.12, `PYTHONUTF8=1`):

- Full suite: `python -m pytest -q --cov=engine --cov=app --cov=data
  --cov-report=term --cov-fail-under=80` — 35 passed, 82.94% coverage
  (this report includes the UI test module).
- `python -m coverage report --omit='*/tests/*' --fail-under=80`
  — 81% for application code, threshold passed.
- Two subsequently added regressions: `python -m pytest -q
  tests/test_pipeline_contract.py::test_loader_reports_missing_required_column
  tests/test_pipeline_contract.py::test_real_engine_connects_to_streamlit`
  — 2 passed. The missing-column case was first reproduced as a TypeError,
  then changed to a readable ValueError.
- `python -m compileall -q engine data app tests` — passed.
- `python -m pip check` — no broken requirements.
- `python -m pip_audit --local --timeout 15 --progress-spinner off`
  — no known vulnerabilities after updating local venv pip to 26.2.1.
- No private IEK spreadsheets, task DOCX, generated CSVs or approval JSONs are
  tracked. Code review found no HIGH/CRITICAL regression.
- Standalone server health probing was blocked by the execution environment;
  UI runtime verification used Streamlit AppTest instead.
- Lint/typecheck tools are not configured; they were not claimed as passing.
