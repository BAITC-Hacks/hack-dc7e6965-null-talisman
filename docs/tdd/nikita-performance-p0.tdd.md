# TDD evidence: Nikita performance P0

## Source and goal

Source: [`docs/PLAN-2.md`](../PLAN-2.md), Nikita P0.

The change must reduce repeated full-table work in `recommend()` and
`sku_series()`, keep recommendation values unchanged, and make the generated
critical queue a useful 5–15% minority while preserving the live checks.

## RED checkpoints

| Commit | Test | RED result |
|---|---|---|
| `7fddd06` | `tests/test_pipeline_performance.py` | 2 failures: both `recommend(category=...)` and `sku_series()` sent category A and B sales into one-off detection |
| `68234c4` | `test_generated_stock_keeps_critical_share_actionable` | failed on the pre-fix generator: `120/306 = 39.2% critical` |

## GREEN implementation

- `bf50339` scopes context to all SKUs in the selected category, retains
  relevant BOM parents until expansion, and then removes non-target sales.
- The recommendation loop builds `(sku, warehouse)` group maps once and
  preaggregates recent means, lost demand, one-off totals, stockout days and
  transit ETA.
- The rebase preserves `origin/main`'s `itertuples()` stock-loop optimization.
- `sku_series()` builds history for the target SKU's entire category across
  both warehouses. This preserves the category seasonal index.
- Schema-less empty sales and stockout frames remain accepted.
- `2c734b4` derives stock from each warehouse's recent daily demand and assigns
  35–90 days of cover. Explicit `DEMO-CRITICAL` and `DEMO-TRANSIT` overrides
  remain unchanged.

## Verification

All commands were run on Windows from the repository root with `.venv` and
UTF-8 mode.

| Check | Result |
|---|---|
| Pipeline regressions | `4 passed in 0.71s` |
| Generator tests | `7 passed in 24.17s` |
| Final full suite after resolving the overlapping `origin/main` pipeline commit | `76 passed in 204.97s` (the original 40 remain green and the combined branch adds coverage) |
| Full suite with coverage gate | `76 passed`; total coverage `93.86%` (`>=80%`) |
| Live checks on a fresh generated dataset | `5/5 passed`, no loader warnings |
| Generated urgency mix | critical `37/306 = 12.09%`; high `34/306 = 11.11%` |
| Static/runtime sanity | `compileall` passed; `pip check` reported no broken requirements; `git diff --check` passed |
| Independent review | Python reviewer and code reviewer: APPROVE, no CRITICAL/HIGH/MEDIUM findings |

The profiler also loaded the HEAD implementation and the working implementation
in separate in-memory modules. `pandas.testing.assert_frame_equal` passed for
the full recommendation table, category+warehouse filtering, `sku_series()`
and the BOM-parent case.

## Performance evidence

Double-run wall-clock measurements on the same local demo data:

| Scenario | Before | After |
|---|---:|---:|
| `recommend()`, all positions | 4.673 / 4.786 s | 3.400 / 3.381 s |
| category + warehouse | 2.271 / 2.336 s | 0.429 / 0.402 s |
| `sku_series()` | 2.106 / 2.129 s | 0.283 / 0.277 s |

After rebasing onto the team's latest `demand.py`, `forecast.py` and UI work, a
freshly generated 155,794-sale dataset measured 3.116 s, 0.363 s and 0.214 s
respectively. The live five-scenario suite took 45.775 s and remained 5/5.

The filtered recommendation and card targets are closed. The full-result
`<=2 s` and live-check `<=30 s` targets remain open: the residual profile is
about 0.82 s in `detect_and_trim_oneoffs`, 0.78 s in
`monthly_clean_series`, and 0.97 s across 306 `forecast_sku` calls. Those
functions are in Abduali's `demand.py` / `forecast.py` ownership area in
`PLAN-2.md`; changing them was intentionally kept out of this branch.
