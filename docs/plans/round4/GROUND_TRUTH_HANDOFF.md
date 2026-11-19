# Round 4 — items for the ground-truth agent

Round 4 found these in `synthetic_traps_v1`'s answer key and tools. The app is right in each
case, by the owner's rulings; the app agent never edits the key or the tools. Evidence and the
owner's decisions: [FINAL_REPORT.md](FINAL_REPORT.md) §1.

| # | What | Where | Why |
|---|---|---|---|
| 1 | `t_text.notes`, `t_text_ch.notes`: the key expects FREE_TEXT, and on ClickHouse a TRANSFORMATION lineage and a quality-report row | key | FREE_TEXT is never inferred ("b7. a"). The app now gives `'caf\xe9'` its `encoding` error row in an unconfigured column (D33). |
| 2 | `Bonaire, Saint Eustatius and Saba`, `Palestinian Territory`: the key expects `BQ`, `PS` | key | Both forms are GeoNames only; "b4. a" keeps them unrecognised, with an error row (`not_in_standard`). |
| 3 | Locale run, phone `020 7946 0958`: the key expects AMBIGUOUS | key | The run's job country is US; the number is not valid for US (libphonenumber 8.13.55). ADR-006 makes it INVALID. |
| 4 | `XYZ` classed `unclassified` | `tools/score.py::ERROR_MESSAGES` | Add the D29 message `not an ISO 4217 currency, or a reserved code (XXX no currency, XTS testing): replace it with a real code such as USD` as `not_in_standard`. Other messages added after `ccc2fdf` are not checked. |
| 5 | The resume variant never reaches its kill points | `tools/run_driver.py`, `truth_resume/kill_points.json` | The job takes 4.9 s and the driver polls every 0.5 s. A row-count kill point, or a slower run, reaches them. The app's own test is `tests/integration/test_resume_after_kill_live.py`. |
