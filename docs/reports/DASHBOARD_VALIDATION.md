# Phase 7 · Interactive Tourism Intelligence Dashboard

Implemented five responsive React/TypeScript/Tailwind screens over the existing
FastAPI/SQLite application: Overview, Destination Explorer, Agent Activity,
Marketing Proposals, and Research Evidence. No paid API request was made for
Phase 7 validation. Nothing was pushed or published.

## Actual SQLite metrics

| Metric | Dashboard / database |
|---|---:|
| Stored photograph source records | 297 |
| Historical Afaq / live Flickr | 197 / 100 |
| Candidate geographic areas | 90 |
| Assigned / unassigned photo records | 144 / 153 |
| Verified destinations / attractions / region context | 5 / 4 / 1 |
| Relevance: relevant / irrelevant / uncertain / not evaluated | 3 / 4 / 18 / 272 |
| Area associations: provisional / ambiguous / not researched | 4 / 1 / 85 |
| Stored agent runs / INVESTIGATE decisions | 1 / 1 |
| Actual saved proposals / pending drafts | 0 / 0 |

The nine destinations/attractions include verified parent destinations; they are
not nine newly identified photo clusters. The tenth verified entity is geographic
region context. Four named associations remain provisional, one area ambiguous.
No cluster is silently renamed.

Regional bars use the persisted photograph `region` field: ten source observations
each for North, South, East, West and Central; 247 have no normalized region value.
Those 247 are shown explicitly as unspecified, not silently assigned from titles
or assumed to have no geography. Cluster-level supporting geographic metadata
remains available separately. Counts and positive sentiment are not demand measures.

## Functional implementation

- Cohesive forest/sand identity, custom SVG mark, responsive sidebar/navigation,
  real-data regional bars and relevance donut, source counts and decision categories.
- Searchable/filterable geographic areas and separate verified entity catalogue,
  including parent destination/region links and authoritative provenance.
- Evidence dialogs show original cluster IDs, precise association uncertainty,
  accessible image previews or honest fallbacks, capture/upload timestamps,
  stored visual categories/scores, distinct photographers, engagement and sentiment
  kept separate, source links, and JSON evidence export.
- Actual chronological agent history, tools and stored results, referenced claims,
  decision explanations, uncertainties and the existing Phase 6 quality-audit warning.
  Private reasoning and unvalidated raw model decisions are excluded from responses.
- Explicit agent confirmation with limits/ledger, one worker, persistent UUID
  idempotency keys and real callback progress. Cached decisions remain cached;
  no page-load search/LLM request, paid automatic retry, or automatic restart resume.
- Actual English/Arabic proposals, proper RTL content, explicit approve/reject
  confirmations and final persisted reviews. No production sample proposals were
  created to fill the empty screen. Approvals do not publish campaigns.
- Research differentiates stored live Tavily assessments from historical observations
  and cached raw Tavily search responses, with timestamps, publishers, excerpts,
  coverage and limitations. The search cache includes additional agent research;
  retrieved excerpts are not presented as identity or coverage assessments.

## Automated and local validation

- **134 Python tests passed:** original 124 plus ten focused API cases including
  read-only connections, metric accuracy, immutable approvals/rejections,
  review persistence into agent memory, idempotent submissions, explicit consent,
  origin checks, concurrency, safe failures, unsafe-budget rejection, interruption
  after restart, missing data and secret redaction. Agents are mocked in API tests.
- **Seven frontend tests passed:** rendering without mutations, cancel/confirm agent
  flow, single scoped submission, Arabic RTL and approval confirmation, backend
  errors, broken-photo fallback, and separating search excerpts from identity assessments. Vitest/jsdom fixtures exist only in tests;
  native dialog methods are polyfilled, so these are not full-browser tests.
- **TypeScript compilation and Vite production build passed.** Production JS is
  about 281 kB (85 kB gzip); CSS about 41 kB (10 kB gzip). Test fixtures are not
  imported by the production entry point.
- Every one of the **90 geographic area detail endpoints** returned valid data.
  **16 locally cached photo previews** in those groups returned valid image
  content. No new Flickr image download or external research was required for this
  check. Other previews use existing Flickr delivery metadata where available.
- Running loopback FastAPI health, Vite HTML and Vite's `/api` proxy all returned
  HTTP 200; the proxy returned the exact 297-photo/90-area database inventory.
- Before/after row counts and SHA-256 checksums match for **all 33 pre-existing
  tables**, including all 297 photos, original analyses, sentiments, mappings,
  research, agent runs and drafts. SQLite integrity is **ok**, foreign-key
  violations **zero**. No real jobs or review records were inserted during tests.
- Configured keys were absent from read API responses and the frontend build.
  The real `agent_requests` and Tavily observation tables did not gain any rows:
  **zero additional OpenAI/Tavily usage**.

The connected browser host reported unavailable; the native Chrome inspection
also timed out. Consequently, no actual browser screenshot, visual inspection,
or full-browser responsive/keyboard verification is claimed. Rendering/interactions
were checked in jsdom and the actual HTTP/API integration was checked separately.

## Preservation and operation

New tables are only `dashboard_agent_jobs` and `dashboard_proposal_reviews`.
Original draft status/content are unchanged; dashboard `effective_status` reads
the separate review record. Agent memory also reads those reviews. Read APIs use
SQLite `mode=ro` and `query_only`; only explicit mutation routes open writable
connections. Existing services gained an optional read-only initialization path.

Run a single local backend process. Startup marks unfinished dashboard jobs
interrupted, never silently resumes paid work. The UI's confirmation, custom local
action header and origin checks are safeguards, not production authentication.
Reviewer names are self-declared. Public deployment requires authentication and
production queue handling. Recent run/job lists are limited to 20; destination
groups reflect the latest saved geographic snapshot. Evidence remains incomplete
and must be reviewed before marketing decisions.

From the repository root, terminal one:

```bash
cd path/to/ATIA
.venv/bin/uvicorn atia.api.main:app --host 127.0.0.1 --port 8000
```

Terminal two:

```bash
cd path/to/ATIA/frontend
npm ci
npm run dev
```

Open **http://127.0.0.1:5173**. All credentials stay in the root `.env`, server-side.

Validation commands:

```bash
# Repository root
.venv/bin/python -m pytest -q
cd frontend
npm test
npm run build
```

Details: `frontend/README.md`. Machine-readable preservation/metric proof:
`data/research/phase7-validation.json`; baseline: `phase7-baseline.json`;
SQLite backup: `data/atia-before-phase7.sqlite3`. Data artifacts remain ignored.
