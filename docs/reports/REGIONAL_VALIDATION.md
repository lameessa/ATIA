# Regional collection validation

Run ID: `f4b2abc4-5db8-4acf-9d08-0f39ca328c8c`

| Region | New photos | Shortfall | Duplicates | Seconds |
|---|---:|---:|---:|---:|
| North | 10 | 0 | 0 | 4.63 |
| South | 10 | 0 | 0 | 4.93 |
| East | 10 | 0 | 4 | 4.47 |
| West | 10 | 0 | 25 | 4.86 |
| Central | 10 | 0 | 10 | 4.6 |

Total regional run time, including country resolution and license lookup: **24.45 seconds**.

All 50 photo IDs were absent from both sources before collection. Each row passed the Flickr Saudi country check and its region matches the verified coordinates. All new rows have upload and capture dates. The 197 historical rows match their pre-run checksum exactly (excluding the new nullable region column); all 50 pre-existing live records remain stored. Database totals: 100 live + 197 historical = 297 records. SQLite integrity check passed.

Tests: 23 passed. No model, agent, or frontend implementation was added. See README for the coordinate sampling scheme and coverage limits. Local JSON report: `data/regional-report.json`; local pre-run backup: `data/atia-before-regional.sqlite3`.

The first broad-box trial was stopped with zero insertions because neighboring-country candidates dominated North. Focused coordinate cores yielded the results above; the run time reported here measures the completed five-region pass, not implementation/debugging time.
