# TDD evidence: real IEK import cleanup

## Source and user journey

Source: user report from the Streamlit upload flow for the supplied IEK XLSX
workbooks on 23.09.2026.

As a purchasing manager, I want the supplied reports to import without double
counting technical duplicate rows, while conflicting constraints still stop
the calculation for manual review.

## RED / GREEN checkpoints

| Behavior | RED commit and result | GREEN commit and result |
|---|---|---|
| Exact duplicate transit rows are counted once | `e6c3d29`: the importer raised `код товара повторяется` | `d1da665`: exact normalized rows are removed; different rows for the same SKU remain rejected |
| Repeated MOQ metadata with the same article and constraint is unambiguous | `565e7a6`: the importer rejected both safe and conflicting duplicates | `a0afaba`: safe metadata duplicates are collapsed; differing article or MOQ remains rejected |
| `#N/A` in the known IEK MOQ column means that the constraint is absent | `cbd7af9`: `#N/A` raised a nonnumeric-value error | `ce0a77a`: IEK `#N/A` uses documented `MOQ 0`; other text remains invalid |
| Untrusted workbook inputs have resource budgets | `bfee990`, `c464bb1`: oversized packages, excessive cell products and uncached numeric formulas were accepted | `dbc0e01`: per-file archive, per-sheet cell and aggregate package limits apply; uncached numeric formulas fail closed; only the known IEK marker receives a default |

## Test specification

| # | Guarantee | Test | Result |
|---|---|---|---|
| 1 | Whitespace-only differences in otherwise identical transit rows cannot double the quantity | `test_transit_import_deduplicates_only_identical_rows` | PASS |
| 2 | Different transit quantities for one SKU are not silently merged | `test_transit_import_rejects_conflicting_rows_for_one_sku` | PASS |
| 3 | MOQ rows with the same supplier article and constraint are collapsed even if descriptive metadata differs | `test_moq_import_deduplicates_matching_constraints` | PASS |
| 4 | Conflicting MOQ values for one SKU stop the import | `test_moq_import_rejects_conflicting_constraints` | PASS |
| 5 | `#N/A` receives the safe default and a visible warning | `test_moq_import_treats_na_marker_as_missing_constraint` | PASS |
| 6 | Unknown text in a numeric MOQ field remains an error | `test_moq_import_still_rejects_unknown_text_constraint` | PASS |
| 7 | Unknown supplier formats cannot turn `#N/A` into a default | `test_na_marker_is_not_a_default_for_unknown_supplier_format` | PASS |
| 8 | Compressed and expanded XLSX size budgets reject oversized input | `test_inspection_rejects_file_above_safety_limit`, `test_inspection_rejects_excessive_expanded_size` | PASS |
| 9 | Worksheet row budgets stop unbounded materialization | `test_import_rejects_worksheet_above_row_limit` | PASS |
| 10 | File count, archive members, columns and aggregate budgets are bounded | `test_inspection_rejects_package_above_total_budget`, `test_inspection_rejects_file_count_members_and_columns` | PASS |
| 11 | Per-sheet and aggregate cell products are bounded | `test_import_rejects_worksheet_above_cell_budget` | PASS |
| 12 | A numeric formula without a cached result cannot silently become zero | `test_import_rejects_formula_without_cached_numeric_value` | PASS |

Command: `python -m pytest app/tests/test_partner_import.py -q` — `22 passed`.

## Real-file verification

The six local IEK workbooks were read through `app.backend.load_partner_files`
with calculation date 23.09.2026. No source workbook was modified or committed.

- seven normalized-identical transit rows were removed;
- one repeated MOQ row with the same article and constraint was removed;
- fifteen `#N/A` MOQ values received `MOQ 0` with a warning;
- canonical tables contained 78,816 sales rows, 2,853 stock rows, 306 transit
  rows and 3,185 product records;
- the real pipeline returned 2,853 recommendation rows, 772 with positive
  recommended quantity.

Known limitation: the source has no clients, exact stockout intervals or BOM,
so the corresponding five synthetic acceptance scenarios are not claimed for
this real import.
