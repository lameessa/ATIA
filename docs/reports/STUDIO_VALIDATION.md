# ATIA Tourism Studio redesign validation

## Implemented experience

A warm off-white, forest-green editorial interface with restrained gold accents,
large archive photography, serif headings and exactly three navigation destinations:
Studio (default), Discover, Calendar. Campaigns open in a contextual workspace,
with bilingual copy/RTL, proposed activities, measurement, sources and human review.
Supporting discovery activity and evidence are expandable rather than standalone
technical pages. Mobile navigation, responsive grids, dialog layouts, reduced
motion and image/loading/error/empty states are implemented.

## Actual local data

Read-only validation on the real SQLite database returned:

- **0 campaigns**, **0 legacy proposals**: intentional Studio and Calendar empty states.
- **37 presentation-eligible geographic areas**, **10 verified identity entities**.
  A verified entity is not an authenticated photo-to-attraction association.
- **2 stored agent activities**, including the prior guarded discovery investigation.
- Agent state: **idle**. No investigation or progress is simulated.
- **3 existing curated archive images** used for internal visual context, with
  attribution/permission details and no claim of verified attraction association.
- Named destination heroes remain placeholders because reviewed image associations
  and reuse permissions have not been established. No popularity scores or
  hidden-gem labels were invented to fill the explorer.

Full campaign and approval states were tested only with temporary synthetic test
fixtures and mocked model calls. No real approval decision was changed.

## Backend and moderation checks

Added `GET /api/workspace` and narrowly scoped full-campaign review support.
Original APIs and analytical functionality remain. Full campaign reviews are stored
additively, preserve draft records, and are visible to agent memory. Approvals
recheck current image snapshots, rights and reviewed entity mappings. Header/body
confirmation requirements, origin checks, conflicting final reviews and duplicate
review requests are covered by tests. Request-revision is not exposed because a
real revision workflow is not implemented.

The image endpoint now accepts only existing local, hash-validated snapshots,
rechecking current moderation and explicit uncertain/irrelevant image reviews.
Media descriptors retain source, attribution, license, approval, rights, usage scope
and location-association status. Unknown permissions never become campaign rights.
No external images were ingested. The extension point is provider-neutral; only the
existing Flickr/cache adapter is currently implemented.

All **63 retained live images** returned **404** from presentation preview routes.
Neither rejected [photo] nor pending [photo] appears in workspace output.
Presentation photo queries still return **197 historical / 0 live**. The full
historical dataset is preserved; explicitly uncertain imagery is not selected by
new media components. Removed images remain protected by existing tombstones.

Validation compared all original non-dashboard table rows before and after the
read workflow: **unchanged**. SQLite `integrity_check`: **ok**;
`foreign_key_check`: **0 violations**. Only an additive empty campaign-review table
is introduced in the real database. Existing analytical results, photographs,
comments, destinations, observations and agent decisions were not rewritten.
Local machine-readable results: `data/research/studio-validation.json`.

**No paid OpenAI/Tavily calls** occurred. Combined request-ledger charge difference
was **$0.00**. No recurring jobs, campaign publication or GitHub push occurred.

## Tests and preview

- Backend: **169 passed** (existing suite plus six focused workspace/media/review tests).
- Frontend: **12 passed** (three-item navigation, destinations/filtering, calendar,
  RTL campaign review, confirmation/cancellation, real-state activity, errors,
  rights gate and unapproved/broken/external image handling).
- TypeScript and Vite production build: **passed**.
- Local API `/api/workspace`: **HTTP 200**, actual data and no paid calls.
- Chrome desktop: Studio, Discover and Calendar inspected with the real database;
  Studio and Calendar screenshots reviewed. A media positioning conflict found in
  the first preview was corrected and the Studio hero rechecked.
- Browser automation host was unavailable; native Chrome access was used. Mobile
  breakpoints are implemented but a dedicated mobile viewport was not visually
  verified because the user was interacting with the browser during inspection.

## Remaining limits

There are no real campaigns to populate the cards/calendar yet. Existing schedules
are relative offsets without an absolute launch date, so no dated events or external
publication claims are displayed. External publishing, request-revision and new
external-image ingestion are not implemented. Real campaign generation remains an
explicitly initiated bounded terminal workflow; this frontend does not start paid
agent executions. No frontend API keys or user-entered campaign prompt are needed.

The application remains a loopback-only local demo without authenticated reviewers.
Approval confirmations enforce the local workflow, not identity authentication.
Campaign effectiveness, licenses, Arabic copy and final launch plans need human
validation before any real-world publication.
