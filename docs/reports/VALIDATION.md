# ATIA pipeline validation — 2026-10-30

Validated against the real Flickr REST API and the supplied `Afaq_RawData.json`. No generated photo records were inserted into the project database. Automated tests use isolated temporary databases.

## Collection and persistence

- First successful live run: `atia collect --limit 50` — 50 inserted, 0 duplicates, 7 pages, complete, exit 0.
- Second live pass: `atia collect --limit 50 --max-pages 1` — 0 inserted, 13 duplicates, 1 page. Exit 2 is expected for this deliberately bounded replay: the collector targets new rows, so existing rows do not satisfy the 50-new-row target.
- Historical import: 197 inserted, 0 skipped. Re-import: 0 inserted, 197 duplicates.
- Final database: 50 `flickr_live` + 197 `afaq_historical` = 247 rows.
- SQLite integrity: `ok`. Duplicate `(source, photo_id)` groups: 0.

All 50 live rows have numeric photo IDs, valid coordinate ranges, distinct upload/capture fields, views, license IDs/names, and preserved Saudi country verification responses. Upload and capture date strings parse successfully. 49 have nonempty titles; the remaining title is empty rather than fabricated.

Historical completeness: 197 numeric IDs; 61 coordinate pairs; 192 upload dates, capture dates, view counts, and license IDs. Five entries have unavailable historical info responses, retained verbatim alongside their IDs and regions. This does not establish that those photographs were deleted. Historical license names were not supplied and remain unknown.

## Compatibility fixes

Flickr returned no results from Saudi Arabia place-name lookup. The client now falls back to WOE ID 23424938 and verifies the country identity with `flickr.places.getInfo`. Country-level photo searches returned error 9, “Not a valid place type.” The collector now finds bounding-box candidates and independently requests each candidate's Flickr location. It accepts only a Saudi country ID, or an explicit Saudi country name when the response omits the ID. Neighboring-country candidates are excluded. Flickr geotags remain user-supplied evidence, not independently established ground truth.

The historical importer now handles the actual regional Afaq structure and nested `info.photo` metadata, preserving region labels and original API responses separately from live records.

## Checks

- `python -m pytest -q`: 17 passed.
- FastAPI health/OpenAPI smoke check: passed.
- `atia stats`: 50 live, 197 historical.
- Git ignore checks: `.env`, `data/atia.sqlite3`, and `Afaq_RawData.json` ignored and untracked.
- No push performed. Credentials were read only from local configuration and were not printed.

The first live milestone is complete. No OpenCLIP, agent, campaign generation, or frontend implementation was added. Views are not interpreted as tourism demand.
