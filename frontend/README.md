# ATIA — The Tourism Studio

A campaign-first React + TypeScript + Tailwind interface over ATIA's existing
FastAPI/SQLite services. Navigation contains exactly **Studio**, **Discover**,
and **Calendar**. No campaign or activity fixtures are seeded in the application.

## Run locally

From `path/to/ATIA`, start the backend:

```bash
.venv/bin/uvicorn atia.api.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
cd path/to/ATIA/frontend
npm ci  # only needed for initial dependency installation
npm run dev
```

Open **http://127.0.0.1:5173**. Vite proxies `/api` to the loopback backend.
The existing Python environment is reused; no new runtime dependencies were added.
Keep `.env`, API keys, data and SQLite entirely server-side. The Vite file server
continues to deny `.env`, `data/`, and historical JSON files.

## Experience

- **Studio**: featured campaign or designed empty state, campaign cards with status
  filters, and a review queue. Past investigations sit in a collapsed research history;
  only live or just-requested jobs are announced. "Discover opportunities" and
  "Create Campaign" can start paid research, always behind the cost-confirmation dialog.
- **Campaign workspace**: complete saved English/Arabic content, RTL captions,
  audiences, creative direction, proposed channels/activities/schedule, measurement
  hypotheses and sources. Evidence and uncertainty stay in an expandable drawer.
  The original preliminary proposal format remains readable without inventing
  missing fields. Approve/reject opens explicit confirmation and persists a review.
- **Discover**: verified destinations and geographic-area galleries, search, region
  filters, source details, parent destination context and load-more pagination. Cards
  prefer an approved hero, then the area's own archive photograph (reference only), then
  an abstract atlas plate (`Plate.tsx`) generated from stored id, region and coordinates. Hidden-gem filtering appears only when a non-rejected
  persisted campaign carries a supported opportunity hypothesis. No opportunity scores.
- **Calendar**: visual month navigation plus actual relative content plans.
  Existing campaigns use day offsets after a future approved launch; there is no
  persisted absolute launch date. Plans therefore remain in an undated agenda,
  never fabricated calendar events. Approval never implies external scheduling.

## API integration and safety

`GET /api/workspace` is a read-only, moderation-filtered projection of the existing
photos, geographic groups, identities, legacy proposals, full campaigns and both
legacy/discovery agent runs. No AI/search services are called on load, refresh,
navigation, filtering, opening details or approving drafts. Running jobs are polled
using the same read projection; otherwise the page does not poll.

`POST /api/campaigns/{id}/review` records APPROVED/REJECTED in the additive
`dashboard_campaign_reviews` table, preserving original PENDING_APPROVAL drafts.
Legacy briefs retain `POST /api/proposals/{id}/review`. Both require an explicit
confirmation body and local action header. Full campaign approval additionally
rechecks current approved pixels, reviewed entity associations, and usable license
metadata. Conflicting final reviews return 409; repeated same decisions are
idempotent. Unavailable actions (revision, publishing, external scheduling) are absent.
Review status is reflected in agent memory without overwriting the draft.

This remains a local demonstration with no authentication: action headers and
confirmations do not establish reviewer identity. Bind to loopback; authenticated
reviewers and stronger deployment controls are required before public hosting.

### Extensible media contract

`src/atia/api/media.py` defines the provider interface and normalized descriptors:
provider/source URL, attribution, license, rights status, approval, usage scope and
entity association. `Media.tsx` consumes the same contract independent of provider.
Images need a recorded review as well as a reusable licence (see the main README). Only
reviewed local image routes are rendered; no remote fallbacks.
Rejected/quarantined/uncertain live pixels cannot bypass this route.

Starting the backend writes to its database (startup migrations and job recovery), so use
`ATIA_DB_PATH` with a copy kept inside `data/` for design work. Images only resolve for a
database located beside `data/images`.

Existing curated historical photographs remain available as internal references,
with unknown permissions and provisional associations explicitly labelled. They
are not represented as licensed campaign material. Named destination heroes need
reviewed entity mappings and usable rights; otherwise an editorial placeholder is
shown. Future external providers must implement the same checks plus quarantine
and explicit approval. No Wikimedia/official-library ingestion, image searching,
large download or new external approval mechanism was added in this milestone.

## Files

- `src/App.tsx`, `styles.css`: three-item shell, visual identity, state, review confirmation.
- `src/Plate.tsx`: generated placeholder art for places without approved imagery.
- `npm run format`: Prettier. Fonts are self-hosted through `@fontsource` packages.
- `src/Studio.tsx`, `Discover.tsx`, `Calendar.tsx`: the three navigation experiences.
- `src/CampaignWorkspace.tsx`: contextual bilingual campaign review.
- `src/Media.tsx`, `productTypes.ts`: provider-neutral, approval-aware media/types.
- Existing shared `components.tsx`, `api.ts` and legacy types are reused. Old page
  modules are no longer navigation routes and are not bundled by the new entry point.
- Python `api/workspace.py`, `api/media.py`, `api/dashboard.py`, `api/data.py`, and
  `agents/discovery_storage.py`: minimal projection, media delivery, persistent
  reviews, request-local read caching and review-aware memory.

## Validation

```bash
cd path/to/ATIA
.venv/bin/python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

See [STUDIO_VALIDATION.md](../STUDIO_VALIDATION.md) for actual data, tests, preserved
records, paid-usage checks and limitations. No campaign has been fabricated to
populate the empty workspace.

## Review copy beside another backend

To run a second copy against a disposable database, set `ATIA_REVIEW_ORIGINS` on the backend and
`ATIA_API_URL` and `ATIA_UI_PORT` on Vite. Writes from any other origin are refused.

```bash
ATIA_DB_PATH=data/atia-phase1.sqlite3 ATIA_REVIEW_ORIGINS=http://127.0.0.1:5174 OPENAI_API_KEY= TAVILY_API_KEY= \
  .venv/bin/uvicorn atia.api.main:app --host 127.0.0.1 --port 8010
ATIA_API_URL=http://127.0.0.1:8010 ATIA_UI_PORT=5174 npm --prefix frontend run dev
```
