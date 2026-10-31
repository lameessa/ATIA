# ATIA technical documentation

This is the full engineering record behind the [main README](../README.md): setup, CLI commands, data model, research methodology and development phases, in the order they were built.

## How to read this document

- **It is a build history.** Early sections describe the system as it stood at that phase, so some are superseded. The first four sections below state current behaviour and take precedence over anything later that conflicts with them.
- **Current rules on images:** archive photographs are no longer trusted automatically. Display follows [Image safety and rights](#image-safety-and-rights).
- **Current rules on drafts:** a structurally valid draft is saved and labelled, not discarded. Follow [How drafts are checked](#how-drafts-are-checked).
- **Live Flickr commands** need `ATIA_ENABLE_LIVE_FLICKR=1`, including the older ones shown below.
- **Hidden-gem language** describes a research hypothesis the older agent could test, never an established fact. The current campaign workflow does not make that claim.
- **Files mentioned but not in this repository:** databases, cached images and anything under `data/` are private, local research artefacts.

Validation reports and audits from each phase are in [`reports/`](reports/README.md). The frontend has its own [README](../frontend/README.md).

## Contents

- [Run the demo (no API keys)](#run-the-demo-no-api-keys)
- [How drafts are checked](#how-drafts-are-checked)
- [Live services are optional](#live-services-are-optional)
- [Image safety and rights](#image-safety-and-rights)
- [Setup](#setup)
- [First milestone: 50 live Saudi photos](#first-milestone-50-live-saudi-photos)
- [Historical Afaq import](#historical-afaq-import)
- [Data model and provenance](#data-model-and-provenance)
- [Project layout](#project-layout)
- [Run tests and backend](#run-tests-and-backend)
- [Automated regional collection](#automated-regional-collection)
- [Original single-dimension analysis (legacy mode)](#original-single-dimension-analysis-legacy-mode)
- [Previous three-dimension analysis (research mode)](#previous-three-dimension-analysis-research-mode)
- [Tourism relevance screening (current default)](#tourism-relevance-screening-current-default)
- [Phase three: Flickr comments and Arabic/English sentiment](#phase-three-flickr-comments-and-arabicenglish-sentiment)
- [Phase four: destination intelligence](#phase-four-destination-intelligence)
- [Phase five: promotional coverage research](#phase-five-promotional-coverage-research)
- [Phase 4/5 audit: authoritative entities and live Tavily (current workflow)](#phase-45-audit-authoritative-entities-and-live-tavily-current-workflow)
- [Phase 6: bounded autonomous investigator](#phase-6-bounded-autonomous-investigator)
- [Phase 7: interactive dashboard](#phase-7-interactive-dashboard)
- [Autonomous hidden-gem discovery and complete campaigns](#autonomous-hidden-gem-discovery-and-complete-campaigns)
- [Flickr intelligence (Phase 1 of the opportunity workflow)](#flickr-intelligence-phase-1-of-the-opportunity-workflow)
- [Marketing opportunities (MVP workflow)](#marketing-opportunities-mvp-workflow)

ATIA turns Flickr metadata into evidence-backed, bilingual campaign drafts for Saudi tourism marketers. A person reviews every draft before it reaches the internal Calendar. Nothing is published.

## Run the demo (no API keys)

```bash
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt -e .
atia demo init                                   # creates data/demo.sqlite3 from demo/seed.json
atia demo validate                               # runs the real validator on the stored draft; no model call
ATIA_DB_PATH=data/demo.sqlite3 uvicorn atia.api.main:app --host 127.0.0.1 --port 8000
```

In a second terminal: `npm --prefix frontend ci && npm --prefix frontend run dev`, then open http://127.0.0.1:5173.

The demo shows Discover with its evidence classes and five campaigns written by GPT-4o-mini. Al Qassim was corrected and approved, so it is on the Calendar. Farasan, Rijal Almaa and Bir Hima are drafts with warnings to review. Riyadh is held in Needs Correction because a claim says "popular" with no record behind it, and it cannot be approved until corrected. Counts and drafts are real records; the reviewer's name is replaced by a role. It includes 15 openly licensed photographs (`demo/images`, credited in `demo/images/ATTRIBUTION.md`); each licence covers that photograph only. Places without an eligible photograph show an illustrated placeholder. Without an OpenAI key, Create Campaign on another opportunity stops safely and spends nothing.

## How drafts are checked

Structurally valid drafts always reach Studio. Blocking errors (malformed structure, unsupported factual claims, invented figures, unsafe terms) stop approval until a person corrects them. Warnings (promotional wording, proposed KPI targets) are shown to the reviewer and do not stop approval. Nothing reaches the Calendar without human approval, and nothing is published. Where older sections or documents describe drafts being rejected outright, this section replaces them.

## Live services are optional

Starting the app or adding a key never contacts Flickr. Live retrieval is off by default: commands that call Flickr refuse to run unless you set `ATIA_ENABLE_LIVE_FLICKR=1` for that command. These include `atia collect`, `atia collect-regions`, `atia sentiment`, `atia intelligence restore-images` or `atia opportunities find-images`. OpenAI and Tavily are only called after a person confirms the cost dialog, or runs a paid command with its explicit flag. None of this is needed for the demo.

## Image safety and rights

Using a photo's metadata as evidence and showing the photo are separate permissions. Every photograph, archive or newly collected, stays hidden until **all** of these are true (`src/atia/moderation/display.py`):

- Flickr last reported it available, at safety level 0, under a licence that allows reuse (CC BY, CC BY-SA or CC0)
- it has no uncertain or irrelevant visual review
- a person's latest review approves those exact image bytes and confirms they viewed it, that it is safe and that the licence is correct, or `config/reviewed-images.json` records an earlier visual review of those exact bytes and no later review overrides it

The entries in `config/reviewed-images.json` were reviewed by assistants, not people, and each records its reviewer. The app never adds to that file, so newly retrieved images wait in quarantine for a person. They appear in `atia images queue`, and a person's rejection overrides an earlier review.

If any check can't be completed, the image stays hidden. Rejected, uncertain, unreviewed, changed or relicensed images return 404, and the API offers no image URLs for them. All Rights Reserved photos can count as evidence but can't be displayed.

```bash
atia --db <database> images queue
atia --db <database> images review --source flickr_live --photo-id ID --sha256 HASH --decision approve \
  --reviewer "Your name" --reason "Why" --viewed-image --confirm-safe --confirm-licence
```

Sections below describe the research pipeline as it was built, phase by phase. Where older sections or validation documents describe archive photos as trusted or displayable, this section replaces them. Photo IDs were removed from those documents.

## Setup

Python 3.10+:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -e .
cp .env.example .env
```

Set `FLICKR_API_KEY` in `.env` to your own [Flickr application key](https://www.flickr.com/services/apps/create/). Public searches need a key, but no API secret or OAuth login. Never paste credentials into source code. `.env`, local databases, and the historical dataset are ignored by Git. Environment variables override `.env` values.

## First milestone: 50 live Saudi photos

```bash
atia collect --limit 50
atia stats
```

Success means the collector exits with code 0, reports `inserted: 50` and `complete: true`, and `stats` shows at least 50 `flickr_live` rows. Tests use synthetic responses and **do not prove live retrieval**. A real API key and successful network access are required to claim the milestone.

The collector resolves Saudi Arabia using Flickr place lookup, with a verified `flickr.places.getInfo` fallback for country WOE ID 23424938 when name search returns no results. Flickr currently rejects country-level photo search, so the collector searches a broad bounding box (`34,16,56,33`) and checks each candidate with `flickr.photos.geo.getLocation`. Only records whose country WOE ID matches Saudi Arabia, or whose country name explicitly identifies Saudi Arabia when Flickr omits that ID, are retained. Neighboring-country candidates are excluded. Country membership remains Flickr's classification, not independent verification of user geotags. `min_upload_date=0` avoids the implicit recent-only geo window. Results use newest upload first, not popularity ranking.

A run targets 50 **new** rows; duplicates do not count. It paginates at up to 250 candidates/page (50 for the default target), stopping after 16 pages (Flickr's 4,000-result search ceiling), exhaustion, or reaching the target. This is a bounded first sample, not exhaustive or geographically balanced coverage. Exit 2 means the target was not reached; exit 1 means an error. Records committed before an error remain available; rerunning safely skips them. Use a separate database for a fresh sample:

```bash
atia --db data/sample.sqlite3 collect --limit 50 --max-pages 16
```

Network timeouts, HTTP 429/5xx, invalid JSON, and temporary Flickr API errors get up to three attempts with exponential backoff. Invalid keys fail immediately without printing remote messages or credential-bearing request URLs. Missing IDs/coordinates are skipped in live collection. Optional missing metadata becomes null or an empty tag list. Public search returns currently visible photos; a photo may later be removed or made private. No image files are downloaded or assumed available, and the API does not continuously revalidate saved records.

## Historical Afaq import

```bash
atia import-historical /path/to/Afaq_RawData.json
atia stats
```

No API key is needed for import. Supported JSON shapes: a list of records; `photos.photo`, `photos`, `data`, or `records` wrappers containing a list; or an object keyed by photo ID. Common Flickr names (`id`, `dateupload`, `datetaken`, `latitude`, `longitude`) and aliases (`photo_id`, `date_upload`, `date_taken`, `uploaded_at`, `captured_at`, `lat`, `lon`) are recognized. Flickr-style nested dates/title/tags are also supported. Missing historical coordinates are allowed. Malformed rows are counted as skipped; invalid JSON or unsupported top-level structures fail clearly.

The supplied Afaq file groups photo IDs under North/East/Central/West/South, with nested `info`, `favorites`, and `comments` API responses. The importer extracts metadata from successful `info.photo` responses, including nested location coordinates, and preserves the region and original responses in `raw`. Entries with unavailable info remain ID-only historical observations; no deletion is inferred. Unknown fields are preserved in `raw`. Do not silently map an ambiguous generic date to both upload and capture dates.

## Data model and provenance

SQLite stores one row per `(source, photo_id)` with `source` either `flickr_live` or `afaq_historical`. The same ID can exist once in each source, preserving historical evidence separately. Repeated records within a source are ignored; this phase preserves the first observation rather than refreshing it.

Fields include title, coordinates, upload/capture dates, capture precision/unknown flag, views, tags, license ID/name/URL, owner ID, Flickr page URL, collection time, and original metadata JSON. Upload Unix timestamps become UTC ISO strings. Capture datetimes preserve their supplied timezone (often unknown); they are never substituted with upload dates. Flickr capture precision/unknown flags should be consulted before treating a capture date as exact. Historical timezone-free upload strings also retain their unknown timezone.

Views are an observation of Flickr activity, **not evidence of tourism demand**. License metadata is retained for later human review; collecting metadata does not establish permission to reuse an image in a campaign. A missing license is unknown, not permission.

## Project layout

- `src/atia/collectors/flickr.py`: official REST client, Saudi country resolution, retries, pagination, collection report.
- `src/atia/collectors/historical.py`: offline Afaq JSON import.
- `src/atia/models.py`: shared schema and normalization, including separate date fields.
- `src/atia/storage/sqlite.py`: parameterized SQLite persistence and source-aware deduplication.
- `src/atia/config.py`, `cli.py`, `__main__.py`: environment settings and command-line entry points (`atia` or `python -m atia`).
- `src/atia/api/main.py`: minimal FastAPI health endpoint and read-only photo listing.
- `src/atia/vision/`: pretrained image retrieval, analysis, and result storage; `src/atia/agents/`: bounded investigation and draft proposals; `frontend/`: React intelligence dashboard and proposal review.
- `tests/`: offline normalization, persistence, provenance, API failures, search parameters, pagination, 50-record collection, and import tests.
- `requirements.txt`, `pyproject.toml`: dependency ranges and installable package configuration.
- `.env.example`, `.gitignore`, `data/`: local configuration and ignored data storage.

## Run tests and backend

```bash
python -m pytest -q
uvicorn atia.api.main:app --reload --host 127.0.0.1
```

Visit `http://127.0.0.1:8000/docs`, `/health`, or `/photos?source=flickr_live&limit=50`. This is a local development backend without authentication; deployment is outside this phase.

Official references: [photo search and metadata extras](https://www.flickr.com/services/api/flickr.photos.search.html), [place lookup](https://www.flickr.com/services/api/flickr.places.find.html), [license lookup](https://www.flickr.com/services/api/flickr.photos.licenses.getInfo.html).

## Automated regional collection

```bash
atia collect-regions --per-region 10 --max-pages 16 --region-seconds 180
```

This independently searches North, South, East, West, and Central, targeting **10 new photos in each**. Progress goes to stderr; the final JSON report goes to stdout and includes actual counts, shortfalls, duplicate encounters, stop reasons, saved IDs, a run ID, and elapsed seconds. To save the report locally:

```bash
atia collect-regions > data/regional-report.json
```

The versioned `saudi-coordinate-zones-v1` sampling scheme uses these focused longitude/latitude search boxes within its assignment zones:

| Region | Minimum longitude | Minimum latitude | Maximum longitude | Maximum latitude |
|---|---:|---:|---:|---:|
| North | 36 | 27 | 45 | 30 |
| South | 40 | 16.5 | 45 | 21 |
| East | 48 | 22 | 50.5 | 28 |
| West | 37 | 21 | 42 | 27 |
| Central | 42 | 21 | 48 | 27 |

The search boxes focus on Saudi cores to reduce neighboring-country traffic and do not provide exhaustive regional coverage. These are approximate geographic sampling zones, **not official administrative regions**. Assignment is deterministic: East is longitude >=48; elsewhere South is latitude <21, North is latitude >=27, and the middle band splits into West (<42 longitude) and Central. This resolves shared box edges without double assignment. Saudi membership must independently pass the Flickr country check; boxes alone are insufficient.

The regional collector skips IDs already present in **either source** before making location requests. It validates candidate coordinates, fetches country/location metadata, assigns the region from that verified location, and commits each accepted photo immediately. No manual photo IDs are used. A nullable `region` column is added automatically to existing databases; previous rows are not reclassified or overwritten. New regional rows preserve `collection_run_id`, `region_scheme`, `collection_region`, and country evidence in `raw`.

Searches fetch 50 candidates/page, at most 16 pages/region. The per-region budget is checked between calls; an in-flight request and its bounded retries can exceed that budget. Existing HTTP connect/read timeouts and retry backoff still apply. After three location-request errors within a region it reports a shortfall and continues to the next region. Exhausted searches, malformed metadata, inaccessible locations, or API failures never cause invented results or quota backfilling from another region. Exit 2 means at least one quota was not reached. Duplicate counts represent encounters, not stored duplicate rows.

Implementation: `collectors/regions.py` defines zones; `collectors/regional.py` runs the regional workflow. Original nationwide collection and historical import remain available.


## Original single-dimension analysis (legacy mode)

Install the optional vision environment, then analyze 10 accessible photographs:

```bash
source .venv/bin/activate
python -m pip install -r requirements-vision.txt
atia analyze --legacy --limit 10 --max-candidates 100
```

The first run downloads the ViT-B/32 `laion2b_s34b_b79k` pretrained checkpoint (roughly 600 MB) from Hugging Face through the official OpenCLIP library. Model artifacts are cached under ignored `data/models/`; downloaded image bytes are cached by SHA-256 under `data/images/`. The default device is CPU, with at most four PyTorch threads for reliable local Mac inference. Apple Silicon can optionally use `--device mps`; an unavailable device fails clearly, and CPU remains the fallback command. No training, fine-tuning, or remote image inference is performed.

`FLICKR_API_KEY` is needed for current `flickr.photos.getSizes` lookups using the stored photo IDs. The collector metadata remains unchanged. Retrieval chooses a currently accessible Flickr image size, restricts downloads and redirects to HTTPS Flickr image hosts, limits bytes/pixels and time, decodes the image, handles EXIF orientation, and converts to RGB for model preprocessing. Transient download errors have bounded retries. Broken, inaccessible, or unsupported photos are recorded as unavailable without inferring deletion; the batch continues through additional candidates until 10 successes or the candidate cap. Images are not assumed available merely because a historical record exists. Storing an image for analysis does not establish campaign reuse permission.

Progress goes to stderr. JSON results go to stdout:

```bash
atia analyze --legacy --limit 10 > data/vision-report.json
atia analyze --legacy --limit 10 --source afaq_historical
```

Successful analyses are skipped on later runs for the same source/photo, model, checkpoint, and prompt version; subsequent runs analyze new candidates. Live records are prioritized by default. A photo ID encountered in both sources is attempted only once per batch. Failed attempts remain retryable. Exit 0 means the requested batch completed, exit 2 means a shortfall, and exit 1 means setup failed.

Tourism descriptions cover mountains, deserts, beaches, forests, historical architecture, cultural landmarks, and urban landscapes, plus an `other` comparison for unrelated scenes. Prompts are in `vision/prompts.py` and versioned by a content hash. Both image and text embeddings are L2-normalized; their dot products are **cosine similarities, not calibrated probabilities, proof of category membership, aesthetic assessments, or measures of tourism demand**. Top categories are relative to the supplied descriptions and can be wrong. A forced top result may be weak; inspect all scores before interpreting it. No softmax probabilities are generated.

SQLite adds two tables without updating any photo rows:

- `visual_analyses`: source/photo foreign key, model/checkpoint, prompt text/hash, all eight scores, top three categories, image checksum/URL/path/dimensions, library version, device, run ID, and analysis timestamp.
- `visual_attempts`: success, unavailable, or inference-error status with source/photo, timestamp, run ID, and safe error reason. Availability failures never label a photo deleted.

Code: `vision/images.py` retrieves images; `vision/model.py` loads and runs OpenCLIP in evaluation/inference mode; `vision/pipeline.py` manages batches; `vision/storage.py` persists results. The original collection commands do not import OpenCLIP or require its optional dependencies.

Run all tests with `python -m pytest -q`. Vision tests use isolated test doubles and image fixtures, so they require Pillow but no model download. Install the vision requirements to include them; tests explicitly skip when Pillow is absent. Live execution results are reported separately from these offline tests.

References: [official OpenCLIP usage](https://github.com/mlfoundations/open_clip), [Flickr image sizes](https://www.flickr.com/services/api/flickr.photos.getSizes.html).


## Previous three-dimension analysis (research mode)

```bash
atia analyze --unscreened-dimensions --limit 10 --batch-size 4 --thresholds config/vision_thresholds.json
```

`analyze --unscreened-dimensions` produces three independent dimensions using the same pretrained ViT-B/32 checkpoint. The old single-dimension tables and results remain available with `--legacy`. No photo rows or Flickr capture timestamps are rewritten.

- **Environment:** urban, desert, mountain, coastal, forest, rural, historical, cultural. Store every score and the strongest category. Emit an accepted label only when its cosine similarity meets `environment_min` and its lead over the runner-up meets `environment_margin`; otherwise the label is null and uncertain, while the strongest match remains visible.
- **Elements:** trees, vegetation, cars, roads, buildings, people, water, rock formations, sand, traditional architecture. Each score independently meets or misses `element_min`; any number of possible matches is allowed. A below-threshold result is uncertain, **not evidence of absence**. This is image-level comparison, not object detection, counting, or localization.
- **Conditions:** daytime, nighttime, sunrise, sunset, cloudy, foggy. Preserve all scores and per-label possible matches. Resolve a lighting label only above `condition_min` and `lighting_margin`; weather can coexist with lighting. Similar sunrise/sunset or day/night scores leave the lighting label uncertain. Unsupported weather is unknown, not an inference that the sky is clear. `partial_uncertain` indicates that only part of the condition assessment is supported.

The default cosine minima are 0.25 and margins are 0.03. These are **uncalibrated starting heuristics**, not validated accuracy guarantees, probabilities, or tourism-demand measures. A `possible_match` is tentative. Tune the JSON configuration against human-reviewed photographs; thresholds accept finite numerical values only. Defaults are also built into the code when `--thresholds` is omitted. Threshold definitions and a configuration hash are stored with every result.

All 24 text prompts are encoded once per model load. Images are encoded together in batches (default 4), then one matrix multiplication compares them with all prompts. Smaller `--batch-size` reduces memory use. `vision/dimensions.py` contains the prompt definitions, interpretation rules, and content hashes; `dimensional_model.py` provides image batching; `dimensional_pipeline.py` orchestrates retrieval/cache/inference; `dimensional_storage.py` persists results.

`visual_dimension_analyses` stores **one row per source/photo/dimension/model/checkpoint/prompt-version/threshold-version**, including dimension-specific prompts, all scores, interpretations, thresholds, OpenCLIP library version, image provenance, device, and timestamps. Three dimensions are committed atomically. The original `visual_analyses`, historical/live source distinction, and all photo metadata remain intact. Inferred lighting describes image appearance only; it never replaces `photos.captured_at` or derives a capture-clock time.

Repeated runs revisit the same stable candidate order and reuse completed dimensional analyses, returning `mode: cached` without image retrieval or model loading. This differs from legacy mode, which skips previously completed records to analyze new ones. A threshold-only change reinterprets saved scores without image inference and stores a separate threshold-version result. Prompt changes require new inference. Cache hits describe the saved image snapshot and do not establish current Flickr availability. Failed or incomplete analyses remain retryable. Batch reports distinguish newly analyzed, cached, and reinterpreted photos and report elapsed time and errors.

```bash
atia analyze --unscreened-dimensions --limit 10 --batch-size 4 > data/dimensions-report.json
# The same command reuses completed results:
atia analyze --unscreened-dimensions --limit 10 > data/dimensions-cache-report.json
python -m pytest -q
```


## Tourism relevance screening (current default)

```bash
atia analyze --limit 10 --batch-size 4
```

The default command now prepares a stable, region-balanced sample and screens it **before** detailed destination classification. `--source` restricts sampling if requested. `--sample-id` reuses a prepared sample. `--limit` counts screened images, not accepted destinations; a report with uncertain images is still a completed screening run. Use the explicit `--legacy` or `--unscreened-dimensions` flags only for controlled research comparisons. The old `--thresholds` option applies to unscreened research mode; screening uses its frozen, versioned policy.

Outcomes:

- `relevant` / `eligible`: candidate destination imagery; permit the new detailed analysis.
- `irrelevant` / `excluded`: dominant irrelevant content; exclude only from destination analysis. Never delete or update the original photo or earlier analyses.
- `uncertain` / `needs_review`: ambiguous or weak evidence. Retain for review, defer detailed destination analysis, and do not silently treat as irrelevant.

`vision/relevance_prompts.py` provides versioned positive destination prompt ensembles (landscapes/natural attractions, heritage, architecture, public spaces, cultural attractions) and alternative ensembles (advertisements, portraits, selfies, products, screenshots, unrelated scenes). Each category averages the cosine similarities from its two templates. Compare the strongest destination category with the strongest irrelevant category. The winner must have cosine >=0.25 and a lead >=0.03; otherwise abstain. These starting heuristics were fixed before this sample was reviewed/predicted and were **not tuned** to increase acceptance. They are not calibrated probabilities or measures of tourism demand.

Revised environment prompts use shorter, consistent wording and compare against non-landscape controls. Element prompts include singular/group variants and alternative scenes, supporting multiple possible matches. Conditions compare lighting with indoor/obscured-context alternatives and cloudy/foggy with clear-sky/unobservable-sky/smoke-trail alternatives. Controls are not verified absence detectors; CLIP can still miss objects or mishandle context. Similarity minima remain 0.25 and margins 0.03; these are initial uncalibrated rules, not proven accurate thresholds. Old prompts and outputs are preserved.

### A fixed, reviewable validation sample

```bash
atia prepare-review --per-region 3 > data/relevance-sample.json
# Use the returned sample_id:
atia screen regional-59fdf9a7ed13bc6f --batch-size 4
atia review-report regional-59fdf9a7ed13bc6f \
  --reviewer assistant-visual-review-v1
```

The validation sample uses a fixed seed and source/ID hashes, prefers live/historical coverage where available, avoids duplicate IDs, and replaces candidates only for unavailable imagery, not based on predictions. The 15-image regional slice has three accessible snapshots per region. Historical region labels are retained provenance and have not been independently reverified. The optional prior ten-image audit is a **separate regression stratum**, not additional representative regional sampling. `--no-audit` omits it. Repeated preparation reuses the pinned manifest. Prior downloaded images may be reused as checksum-verified snapshots; this does not establish current online availability. Inaccessible candidate attempts are retained without assuming deletion.

The report exporter creates `data/relevance-review/previews.html` with offline embedded image previews, review reasons, predictions, and supporting scores; `evaluation.json` contains confusion matrices and per-image details. `RELEVANCE_VALIDATION.md` is the readable summary. Decisive disagreements and abstentions on clear labels are reported separately. Treating an uncertain review as definitively relevant/irrelevant also needs review.

Current review labels are explicitly **assistant visual inspections, not independent human ground truth**. They were recorded before new predictions. A person should confirm/revise them before calibration or accuracy claims. To add independent reviews, create a JSON file with `reviewer`, `review_type` (for example `human_review` only for an actual person's annotations), and a `labels` list containing `photo_id`, exact `image_sha256`, `label` (`relevant`, `irrelevant`, `uncertain`), and `reason`. Import and compare using:

```bash
atia import-review-labels SAMPLE_ID /path/to/labels.json
atia review-report SAMPLE_ID --reviewer YOUR_REVIEWER_ID
```

Each review is immutable for its reviewer/sample/photo; use a new reviewer identifier for revisions. Image checksums prevent attaching labels to another snapshot. No automatic human confirmation is invented, and review labels do not silently overwrite model predictions or make uncertain images eligible.

### Incremental inference and storage

`image_embeddings` caches normalized float32 image features by image SHA-256 and model/runtime/preprocessing key. The key includes model/checkpoint, OpenCLIP/PyTorch/torchvision/Pillow versions, and preprocessing version. All prompts are encoded once per model load. Relevant and irrelevant comparisons reuse those same image features; only eligible images receive detail comparisons. Completed assessments are cached by source/photo/image/model/prompt/policy versions. A repeated run uses no image retrieval, model load, or image inference. A prompt/policy change reuses compatible image embeddings rather than re-encoding images. Before this stage, embeddings had not been stored, so the existing ten audited images required one new encoding to support changed prompts.

New additive SQLite tables:

- `tourism_relevance`: all decisions, exclusion/review status, prototype and category cosine scores, model specification, prompt definitions/hashes, frozen policy/hash, image provenance, and gated detail results.
- `destination_dimension_analyses`: separately addressable environment, elements, and conditions for eligible images, foreign-keyed to their relevance assessment. No dimension rows are created for excluded/review-pending images.
- `image_embeddings`: reusable image features with model and preprocessing provenance.
- `review_samples`, `review_sample_members`: deterministic selection protocol, regional strata, immutable image snapshots, and unavailable attempts.
- `visual_review_labels`: versioned, image-specific annotations with reviewer identity/type and reasons.

Implementation modules: `screen_model.py`, `screen_pipeline.py`, `screen_storage.py`, `review_sample.py`, and `relevance_review.py`. Existing photo, legacy analysis, dimensional analysis, and attempt tables remain unchanged.

The current small validation has extensive abstention; see `RELEVANCE_VALIDATION.md`. Geographic balance is not semantic coverage or evidence of tourism demand. More independently reviewed positives/negatives, held-out groups, object/lighting labels, and failure examples are needed before threshold calibration. No autonomous decision-making agent, training, or fine-tuning is implemented. Phase-three comment sentiment is described below.

## Phase three: Flickr comments and Arabic/English sentiment

```bash
source .venv/bin/activate
python -m pip install -r requirements-sentiment.txt
atia sentiment --limit 10 --batch-size 16 > data/sentiment-report.json
```

This imports the historical Afaq comment snapshots, prioritizes current relevance-approved photos once, then fills the initial batch from the manually curated historical records across available region labels. It never ranks by views/favorites. The current database's three relevance-approved records are themselves historical Afaq records, not three additional live-source photos. Photo IDs are deduplicated during selection. Up to `max(30, limit * 3)` photo candidates are attempted to reach the requested number with successful public comment API responses. A photo with no comments still counts as accessible; it is not labelled neutral.

Live collection uses official [`flickr.photos.comments.getList`](https://www.flickr.com/services/api/flickr.photos.comments.getList.html), inheriting the REST client's timeouts, transient-error retries, and secret-safe errors. Failed/inaccessible/malformed responses are recorded without inferring deletion. Successful empty responses remain distinct. A comment author's deleted-account flag is retained in raw metadata; it is not evidence that the comment text was deleted.

The pretrained [`cardiffnlp/twitter-xlm-roberta-base-sentiment`](https://huggingface.co/cardiffnlp/twitter-xlm-roberta-base-sentiment) model outputs **positive, negative, neutral**. Its sentiment fine-tuning languages include Arabic and English (plus French, German, Hindi, Italian, Spanish, Portuguese). ATIA intentionally processes Arabic/English only in this phase. The model commit is pinned to `f2f1202b1bdeb07342385c3f807f9c07cd8f5cf8` in `sentiment/model.py`; tokenizer and weights use that exact revision. Local CPU inference is batched and runs without gradients or training. The first run downloads a roughly 1.1 GB model checkpoint into ignored `data/sentiment-models/`. Comment text stays local; only public API/model downloads use the network.

Language identification uses langid across its full language inventory, not a forced Arabic-versus-English choice. Purely nonlinguistic/empty content, too-short text, uncertain language (`<0.8` normalized detection score), Arabic/Latin mixed-script comments, and languages outside ATIA's Arabic/English policy are retained with explicit skip/review statuses and no sentiment label. Arabic script alone is not proof of Arabic: confidently detected Persian/Urdu are skipped. Language scores are heuristic and may be wrong, especially on dialects, transliteration, short praise, names, and code-switching.

Original HTML/text is preserved. HTML is parsed into visible text, not executed. URLs/mentions are normalized for model input following the model card. Input is limited to 256 tokens; truncation is recorded. Sentiment confidence is the model's uncalibrated softmax score, **not** validated correctness, opinion prevalence, tourism demand, or destination satisfaction. Tweet-domain training can misread Flickr award messages, photo-quality praise, sarcasm, dialectal Arabic, and comments about the photographer rather than a place. No field labels neutral because of missing data. No author profiles, views, favorites, or engagement fields feed sentiment.

### Provenance, edits, and incremental processing

- `comment_versions`: canonical `(photo_id, comment_id, content_hash)` versions, original text, extracted text, creation timestamp, and raw comment metadata.
- `comment_observations`: links each version to its historical/live origin and the original source/photo. Matching IDs/text fetched again do not duplicate comment evidence. Different texts for one comment ID remain separate preserved versions.
- `comment_fetches`: success, empty, unavailable, or malformed observations, independent of comment sentiment.
- `comment_sentiments`: detected language/status, sentiment label, confidence/all three scores, pinned model/revision, preprocessing/language versions, runtime, truncation flag, and analysis timestamp. Skipped comments have null sentiment/confidence rather than invented neutral labels.
- `sentiment_destinations`, `sentiment_photo_destinations`: explicit optional destination grouping, separate from region and engagement.

A repeat run reuses successful comment fetches and cached classifications, including skip decisions. Use `--refresh-comments` to discover newly added/edited comments. Reanalysis occurs when the comment content, model revision, language policy, or preprocessing version changes. Failed inference remains retryable. No historical versions are overwritten; absence from a later response is **not** recorded as deletion. Aggregation uses one latest observed version per comment ID, preferring live observations over historical snapshots; historical-only evidence remains identified as such. Consequently aggregates are observed-evidence summaries, not claims about the current complete comment list.

```bash
atia sentiment --limit 10 --refresh-comments
```

### Aggregation and explicit destinations

Reports include per-photo sentiment distributions, language/status coverage, zero-comment photos, historical-only evidence counts, errors, and execution time. Destination aggregation is produced only for explicit mappings, deduplicating comment IDs per photo within each destination. A region is never silently treated as a destination. The current dataset has no such mappings, so destination aggregation initially remains empty.

To supply reviewed mappings, use a JSON list:

```json
[
  {"source": "afaq_historical", "photo_id": "YOUR_PHOTO_ID", "destination_id": "YOUR_REVIEWED_DESTINATION_ID", "name": "Reviewed destination name"}
]
```

```bash
atia sentiment --limit 10 --destination-map /path/to/destinations.json
python -m pytest -q
```

Modules: `sentiment/comments.py` retrieves/imports comments; `text.py` cleans and detects language; `model.py` runs pinned pretrained classification; `storage.py` preserves evidence and caches results; `pipeline.py` selects photos and aggregates results. Existing photo and OpenCLIP tables are never updated. Sentiment is comment-text evidence, not demand estimation. No autonomous agent or frontend is implemented in this phase.


## Phase four: destination intelligence

Build geographic candidate groups and inspect a snapshot:

```bash
atia destinations build --distance-km 1 --min-accuracy 12 > data/destinations/latest.json
atia destinations inspect
atia destinations inspect --destination-id DESTINATION_ID
atia destinations inspect --run-id RUN_ID --destination-id DESTINATION_ID
```

The build writes `DESTINATION_INTELLIGENCE.md` (`--report PATH` overrides it) and adds snapshot tables to the existing database. It makes no network requests, trains/runs no models, performs no LLM clustering, and never updates the photo, comment, AI, review, or explicit sentiment-destination tables. No API key is required for this command. SQLite integrity and foreign-key checks are part of validation/tests.

### Geography and naming

The default policy requires valid nonzero coordinates in the broad Saudi candidate extent, Saudi country metadata, and Flickr accuracy >=12. Unknown/missing coordinates or accuracy, non-Saudi country evidence, coarse accuracy, and contradictory location versions remain unassigned with reasons. Flickr accuracy levels are ordinal metadata, **not error distances or location authentication**. The broad coordinate extent is not a border polygon. Current country checks rely on stored Flickr metadata; false user geotags remain possible. No destination is inferred from a title, region, visual category, or missing location.

Grouping uses Haversine distances and deterministic greedy **complete-link insertion**: every pair within a group must be within the configurable distance. This is a **maximum diameter**, not a DBSCAN radius. It prevents transitive chains from spanning multiple destinations. Conflicting locality IDs or explicit attraction IDs block merging. Different names/scripts without contradictory IDs are retained as contextual variants and flagged for review. The algorithm is lightweight and deterministic for fixed data, but not globally optimal; nearby distinct attractions can still share an area.

Five-region sampling labels, Flickr administrative regions/localities, destination areas, and individual attractions are different fields. By default groups are neutral **Unidentified destination area** candidates with coordinates and Flickr-reported locality context. City names are not treated as verified attraction names; broad regions do not create destinations. Titles and all available place metadata remain in the assignment evidence for review.

If independently reviewed place evidence is available, provide a JSON list using `--places /path/to/places.json`:

```json
[
  {"source":"afaq_historical", "photo_id":"YOUR_PHOTO_ID", "place_id":"YOUR_VERIFIED_PLACE_ID", "name":"Verified place name", "level":"individual_attraction", "verified":true, "reviewer":"Your actual reviewer", "evidence_url":"https://official-source.example/place"}
]
```

The command stores the supplied reviewer/reference; it does not itself verify a URL or invent a reviewer. Group-level verified naming is used only if every member carries the same reviewed place identity; otherwise reviewed names stay candidates inside a neutral area. `destination_area` is also a valid reviewed level. The current run has no such annotations, so **no individual attractions or attraction names are asserted**.

### Stable IDs and evidence snapshots

- `destination_entities`: persistent IDs and policy/anchor provenance.
- `destination_runs`: configuration, photo-input hash, execution summary, and creation time.
- `destination_snapshots`: one group's full evidence per run, including its naming level and uncertainty.
- `destination_photo_assignments`: source/photo-to-group mappings, or explicit unassigned reasons, with extracted geographic evidence.

Initial IDs are deterministic UUID-derived values. Subsequent runs with the same policy reuse identities by greatest membership overlap. Adding a lower-sorting photo does not automatically rename its existing destination. Splits/merges retain one matching ID and parent candidates; old runs remain available. Different distance/accuracy/annotation policies use different namespaces. These are stable candidate-area identities, not guaranteed permanent real-world attraction identifiers. Always retain the run ID when interpreting past evidence.

Aggregates deduplicate photo IDs across source observations and include distinct known photographers with missing-author coverage, source counts, possible visual categories/elements with model/prompt provenance, uncertainty, raw engagement totals and coverage, current-version comment sentiment and skips, successful zero-comment versus missing-fetch evidence, and separate upload/capture bounds. Favorites use the API total, never the length of a paginated favorites list. Capture timestamps keep their supplied timezone/unknown flags and are never replaced by upload dates or lighting labels.

Relevance statuses remain `relevant`, `irrelevant`, `uncertain`, and `not_evaluated`. Only 25 photographs were audited; the rest are **not** assumed irrelevant. Known excluded content can still be geographically assigned, but is explicitly flagged and its dimensional results suppressed from destination visual evidence. Geographic assignment does not make a photograph eligible or prove a destination is tourism-worthy. Historical curated-source counts remain separate from model eligibility.

Sentiment uses latest observed comment versions and one explicit analysis version, avoiding duplicate text versions or mixed model counts. Historical-only observations remain identified; absence from current responses does not imply deletion. No sentiment results means unknown coverage, not neutral opinion. No existing manual destination mapping is overwritten; phase-four groups aggregate sentiment directly without altering the earlier mapping tables.

Photo/photographer counts, views, favorites, and positive comments are evidence inventory—not tourism demand, destination quality, or marketing opportunity scores. Review flags include single-photographer/single-photo areas, near-limit diameters, locality variants, repeated coordinates across photographers, and reviewed/screened irrelevant content. Dense areas may contain several attractions, and all geotags remain unverified against independent geographic evidence.

Implementation: `destinations/geo.py` defines filters and clustering, `storage.py` preserves stable identities and snapshots, `evidence.py` aggregates existing evidence, and `pipeline.py` builds/reports groups. Phase-five promotional research is described below; no autonomous agent or frontend is implemented.

## Phase five: promotional coverage research

The lightweight research tool investigates **existing coverage**, not underpromotion or demand. It reads destination snapshots and adds research tables without changing destination names, mappings, photographs, comments, or AI results. No LLM orchestrator or new dependencies are required.

### CLI and providers

```bash
# Inspect candidates and existing findings:
atia destinations inspect
atia research inspect
atia research inspect --destination-id DESTINATION_ID

# Standalone live search (requires BRAVE_SEARCH_API_KEY in local .env):
atia research run --provider brave --resolutions /path/to/reviewed-identities.json \
  --destination-id DESTINATION_ID
```

`BRAVE_SEARCH_API_KEY` is optional and documented in `.env.example`; never place it in source or command arguments. The Brave adapter uses its official HTTPS search API, header authentication, bounded retries, and timeouts. It does **not** fetch/scrape search engines or destination pages. Missing credentials and denied access produce unavailable status, not fabricated empty searches. Raw API snippets are conservatively treated as leads requiring review, so the live adapter may return insufficient evidence rather than automatically assert promotional coverage.

The completed local validation used the connected OpenAI web search/source-access tool and recorded a curated set of its actual observations. Python can ingest/replay those reviewed observations:

```bash
atia research run --provider evidence-file \
  --evidence-file data/research/web-observations.json \
  --resolutions data/research/resolutions.json \
  --destination-id dest-6d4a76530a295c67 \
  --destination-id dest-9b1561923af55275 \
  --destination-id dest-3bf62e49baff55ee \
  --destination-id dest-33c40f18483657d7 \
  --destination-id dest-bc2ce41bd5235a49
```

These local files contain actual sourced summaries, not simulated results or exhaustive raw SERPs. Replaying a file is **not a new live web search**. Its hash participates in cache identity, and source observation times remain separate from ingestion/research time. A missing exact query is unavailable, never an invented empty result. Current evidence records distinguish readable pages, indexed excerpts, and official map links; blocked/JS-only pages remain limitations, with no access-control bypass. The standalone Brave adapter was tested with mocks but lacks a live credential here.

The CLI selects at most five candidates by evidence readiness (curated historical or relevance-approved photos, usable destination geography, locality context), never Flickr popularity or positive sentiment. `--destination-id` can be repeated to choose specific eligible areas. Generic IDs and neutral cluster names are never accepted as verified attraction names. The Hittin cluster remains unresolved because its titles mix Boulevard World and Boulevard City.

### Verified identity and evidence

Pass `--resolutions` as a JSON object keyed by destination ID. A resolved identity requires `destination_id`, `status: resolved`, `verified_name`, `association_scope`, `match_basis`, and `sources`. Sources use the `Source` dataclass in `research/providers.py`: title, HTTPS URL, publisher, concise evidence summary, access provenance (`page_read`, `search_index_excerpt`, `official_map_link`), kind (`identity_reference`, `promotional_coverage`, `unclassified_search_result`), explicit `subject_match`, scope, and observation time. At least one identity reference must come from an approved authoritative domain. Domain approval and a reviewed file are not independent field authentication; retain how metadata/coordinates support the association and any remaining limitations.

A name is externally verified as a real entity before it is used in queries. Associating a photo cluster with that name is separate and may be less certain. Historic Jeddah is an area, Farasan evidence applies to the broader archipelago, and neither proves a dedicated campaign for one precise photo coordinate. Resolution documents must record that scope. Unresolved identities can retain references and reasons, but are not given cluster-specific promotional conclusions.

Coverage labels:

- `coverage_found`: reviewed, subject-matched promotional evidence with explicit destination scope.
- `no_coverage_found_within_searched_sources`: completed bounded searches yielded no matched promotional evidence. This does not mean no coverage exists online.
- `insufficient_evidence`: unresolved identity, unreviewed leads, or partial/ambiguous research.
- `research_unavailable`: credentials/access unavailable and no completed searches.
- `research_failed`: attempted searches failed technically and none completed.

Every finding keeps research timestamp, destination snapshot, resolution, planned/completed queries, URLs/titles/publishers, concise evidence, access provenance, limitations, and status. `promotional_gap_claim` remains null; low Flickr counts or missing search hits cannot support one. Official tourism listings establish existing public visitor information, not paid campaign reach, quality, recency of every detail, or marketing performance. No exhaustiveness, social-media audit, or Arabic-language search coverage is claimed for this small English-query validation.

### Reusable Python tool and caching

```python
from atia.storage.sqlite import PhotoStore
from atia.research.providers import BraveSearch
from atia.research.tool import research_destination

with PhotoStore("data/atia.sqlite3") as store:
    result = research_destination(
        store, destination_id, provider, resolution=reviewed_resolution,
        ttl_hours=168, refresh=False,
    )
```

`provider` can be `BraveSearch`, `EvidenceFileSearch`, or an agent-supplied implementation exposing `name`, `cache_identity`, and `search(query)` returning validated `Source` dictionaries. This is a tool interface, not an autonomous agent. A future agent must preserve the same identity, source, access, and uncertainty requirements; it cannot turn unreviewed leads into proof merely by calling the function.

Cache keys include tool version, geographic/photo membership scope, identity resolution, and provider/evidence identity. Identical groups can reuse results even after an otherwise unchanged destination rebuild. Changes to cluster scope or evidence invalidate the cache. Cached results retain their original research/source timestamps and snapshot reference; unavailable/failed research is retried. `--refresh` bypasses cache. No API key is persisted.

SQLite additions:

- `promotional_research`: versioned assessment, snapshot linkage, status, identity, queries, limitations, and full JSON result.
- `promotional_research_sources`: deduplicated URLs with source organization, evidence, access type, scope, and source-observation timestamp.

Readable results: `PROMOTIONAL_RESEARCH.md`. Local validation data: `data/research/results.json`, `cache-results.json`, `web-observations.json`, and `verification.json`. Run tests with `python -m pytest -q`. Phase 5 stops here: no Phase 6, orchestration, frontend, model training, or GitHub push.

## Phase 4/5 audit: authoritative entities and live Tavily (current workflow)

The 90 Phase-4 records are **geographic clusters**, not officially named tourism destinations. Their names, IDs, original levels, memberships, and snapshots remain unchanged. Phase-5 recorded name resolutions are retained as historical source-review observations; they are not silently promoted to live verification.

The corrected layer separates:

- **Geographic cluster:** a bounded group of nearby Flickr geotags, possibly containing multiple attractions or false geotags.
- **Verified destination entity:** a broader named tourism place supported by authoritative returned content, for example AlUla.
- **Verified attraction entity:** a named landmark/site within a broader destination, for example Maraya within AlUla. Two nearby attractions remain different entities.
- **Unresolved cluster association:** either several plausible entities, no authoritative name evidence, or only a provisional metadata match. A verified entity name does not authenticate the cluster or its photographs.

### Terminal-only live research

`TAVILY_API_KEY` is loaded through `.env` into the process environment. The key is never printed, persisted in results, placed in source URLs, or sent in the JSON request body. No new SDK or dependency is required.

```bash
atia research run --provider tavily --limit 5 > data/research/tavily-results.json
atia research inspect --provider tavily --destination-id dest-3bf62e49baff55ee
atia research entities > data/research/entity-catalogue.json
```

This Python command directly posts to `https://api.tavily.com/search` with bearer authentication, basic search, bounded results, no generated answer, and no raw HTML collection. It works independently of Codex web tools. Tavily's returned source text is explicitly `tavily_search_content`, not a claim that ATIA directly fetched a whole page. Publishers are identified from known official hosts; unknown hosts retain their hostname. Request IDs, search parameters, returned titles/URLs/content, provider, and actual retrieval timestamps are stored without credentials.

Successful queries are cached in SQLite for seven days, even across terminal processes. Completed assessments also have a seven-day cache. Query/assessment keys include request parameters, rules, candidate plans, provider, and geographic scope; changing interpretation rules can reuse query content without another paid search. `--refresh` bypasses these caches. Cached results keep their original source timestamps and explicitly identify cache reuse. Rate limits and 5xx responses have bounded retries; credential/quota errors, timeouts, and malformed responses produce explicit failure/unavailability. Missing credentials never become an empty successful search.

### Verification versus association

`config/location-research-candidates.json` contains **hints**, not official names. It records possible aliases, expected entity types, parent candidates, and ambiguous cluster metadata. No prior Codex source observations or old `--resolutions` file are accepted as live evidence in Tavily mode.

`research/identity.py` checks an approved authoritative source host, a candidate alias in the returned source title, meaningful returned content, and whole-word type evidence. Generic navigation mentions are insufficient. An authoritative entity name/type can then be recorded. A parent link requires its own authoritative confirmation plus child-source location/relationship context; otherwise it stays unconfirmed. This is an auditable source-extraction rule, not independent field verification or a claim that every official webpage is infallible. Source text may be partial, stale, ambiguous, or operationally inconsistent.

Flickr titles, OpenCLIP categories, and approximate coordinates are only association hints. No current source independently maps these Flickr photo IDs or cluster boundaries to a recognized attraction, so the corrected workflow leaves `confirmed_cluster_name` null. Singleton candidate matches are provisional; the Hittin cluster remains unresolved because its titles can refer to both Boulevard World and Boulevard City. AlUla is a parent destination, while Maraya is an attraction; those entities are not merged. Farasan refers to a broader destination, not a verified fishing spot or precise photo-site boundary. Regions such as Jazan are not automatically tourism destinations.

Coverage is evaluated from authoritative subject-matched visitor/tourism information. It describes existing visitor-facing coverage, not necessarily a paid campaign, publicity reach, current opening hours, destination popularity, or an underpromotion gap. An unresolved mixed cluster cannot receive a cluster-wide coverage conclusion merely because each candidate attraction has coverage. The new `research_status` is `insufficient_evidence` in that case, with candidate-entity findings preserved separately. Existing recorded evidence remains inspectable:

```bash
atia research inspect --provider historical
```

### Additive schema

- `tavily_search_observations`: successful, versioned real API responses, request IDs and cache provenance.
- `verified_location_entities`: stable named entities and explicit destination/attraction/region types.
- `authoritative_entity_verifications`: source URLs/publishers/content, verification status/rule/timestamp, and parent entity/status.
- `cluster_entity_associations`: original cluster/run IDs linked to entity verifications with provisional or unresolved status. Multiple attraction candidates do not rename or merge the cluster.
- `live_location_research`: versioned live-Tavily assessments, entity coverage, ambiguities, failures, and query provenance.
- `historical_research_identity_audits`: annotations of earlier research limitations without changing the historical findings.

`atia research entities` lists direct cluster/entity links separately from provisional links via child attractions. It also distinguishes unresearched clusters from unresolved ones. All existing photo, comment, sentiment, visual, screening, destination mapping, and historical research tables remain untouched.

See `AUTHORITATIVE_RESEARCH_AUDIT.md` for actual validation, source links, and access limits. The first real live terminal run used 16 HTTP requests (plus a separate initial connectivity probe); subsequent rule review reused saved Tavily responses, and the complete replay made zero API calls. That audit did not include Phase 6; the agent implementation follows below.

## Phase 6: bounded autonomous investigator

The official OpenAI Python SDK's Responses API now drives a dynamic function-calling
loop. The model chooses candidate/entity lookup, stored photo/visual evidence,
engagement/sentiment summaries, existing authoritative research, an additional
Tavily query, prior decisions, or saving sourced interpretations. Existing Python
services are reused. Photos are represented by URLs and stored analyses, without
rerunning CLIP or sending original images to OpenAI.

Inside the virtual environment, update dependencies with
`python -m pip install -r requirements.txt`. Add `OPENAI_API_KEY=your_key` to the
local `.env`; never put it in source, CLI arguments, or reports. The existing CLI
loads `.env` automatically. Run from the project root:

```bash
.venv/bin/atia agent run --cluster-id dest-3bf62e49baff55ee
.venv/bin/atia agent inspect
.venv/bin/atia agent inspect --run-id agent-REPLACE_WITH_RUN_ID
.venv/bin/atia agent proposals --cluster-id dest-3bf62e49baff55ee
.venv/bin/python -m pytest -q
```

Each run investigates **one explicit cluster**. Defaults in `.env.example` are
4 LLM requests, 3 tool calls, 1 additional Tavily query, 1,800 output tokens per
request, $0.05 estimated OpenAI cost per run and $0.25 cumulative local cost.
Hard ceilings prevent large runs; no batch command is provided. The default
`gpt-4o-mini` has no hidden reasoning phase. Its official page currently marks it
deprecated; access is account-dependent and no model fallback is silently billed.
Reviewed configurable alternatives are `gpt-5.4-nano` (reasoning `none`) and
`gpt-5-mini` (`minimal`). Unknown prices fail closed. Output caps include reasoning
tokens when applicable. See [official model/pricing documentation](https://developers.openai.com/api/docs/models/gpt-4o-mini).

Before each request an atomic SQLite ledger reserves a conservative UTF-8-byte
token estimate plus protocol margin and maximum output allowance. Successful
usage replaces the reservation with token-based estimated cost; failed or
uncertain calls retain the upper-bound reservation, even after a crash. This
controls calls through this database, **not account-wide billing or actual credit
balance**. Pricing and token estimates cannot promise an exact invoice cap.
Tavily quota/cost is separate. Leave account automatic recharge disabled.

SDK automatic retries are disabled. One explicit 429 retry is allowed, consuming
another request step and reservation; timeouts and other failures stop without
a paid repair loop. Context is bounded. Tool histories remove repeated referenced
payloads without LLM summarization. A context-limited nonreasoning run can resume
with `--resume-run-id RUN_ID` within its **original remaining** request, tool and
spending limits; it never reruns completed tools or uncertain API requests.

Successful identical decisions are cached for 24 hours; repeat runs need no API
request. Fingerprints include current photos, relevant AI/comment records,
identity assessments and relevant Tavily observations. `--refresh` bypasses this
cache and may incur another bounded charge. Prior run/proposal IDs are loaded on
new runs, and full relevant memory is available as a tool. Draft uniqueness by
cluster/evidence fingerprint prevents duplicate proposals on forced reruns too.

Decisions are `CREATE`, `UPDATE`, `INVESTIGATE`, and `NO_ACTION`. Claims must cite
references actually returned during the run. Invalid references, malformed output
or exhausted limits produce `INVESTIGATE`. A targeted guard also rejects observed
unsupported popularity/demand/promotional-gap assertions. It is **not a general
semantic entailment checker**: humans must still assess every claim and opportunity.
Retrieved text is untrusted data; prompt-injection resistance is imperfect.

Drafts require inspected authoritative entities, returned source URLs, all bilingual
Arabic/English fields, explicit uncertainties, and a real previous proposal for
`UPDATE`. Photo counts cannot alone justify a draft. Concepts/audiences are
hypotheses. Every saved proposal has `PENDING_APPROVAL`; no publishing tool exists.
Cluster proximity does not authenticate attraction photos; unevaluated photos
remain unevaluated. Positive comments and engagement do not prove tourism demand.
Missing search results do not prove underpromotion.

New additive tables: `agent_runs`, `agent_requests`, `agent_tool_calls`,
`agent_observations`, `agent_proposals`. These retain goals, timestamps, tool
arguments/results, sourced interpretations, evidence references, decision
explanations, proposal links and estimated usage. Original tables are unchanged.
No private chain-of-thought is stored. `agents/contracts.py`, `tools.py`,
`storage.py`, and `runner.py` implement contracts/limits, service wrappers, memory,
and the bounded loop respectively.

All automated OpenAI calls are mocked. See `AGENT_VALIDATION.md` for the actual
one-location run, cost, source-backed decision, observed model mistake and its
offline correction without another paid call. That validation preceded the Phase 7 dashboard below.

## Phase 7: interactive dashboard

The `frontend/` application uses React, TypeScript and Tailwind CSS. It exposes
Studio, Discover and Calendar using actual SQLite observations. Campaigns are
reviewed in a contextual bilingual workspace with RTL Arabic. Verified identities,
provisional geographic associations, curated archive references and campaign-ready
media remain distinct. See `frontend/README.md` and `STUDIO_VALIDATION.md` for the
current redesign, media rights checks, empty states and validation.

Run in two terminals from this workspace:

```bash
# Terminal 1, repository root
cd path/to/ATIA
.venv/bin/uvicorn atia.api.main:app --host 127.0.0.1 --port 8000
```

```bash
# Terminal 2
cd path/to/ATIA/frontend
npm ci
npm run dev
```

Open **http://127.0.0.1:5173**. Python setup remains `python -m pip install -e .`
inside the virtual environment. Never put API keys into frontend configuration.

Read-only endpoints: `/api/overview`, `/api/destinations`,
`/api/destinations/{cluster_id}`, `/api/research`, `/api/agent/runs`,
`/api/agent/runs/{run_id}`, `/api/agent/policy`, `/api/proposals`,
`/api/agent/jobs`, `/api/agent/jobs/{job_id}`, and cached `/api/images/{source}/{photo_id}`.
Existing `/health` and `/photos` remain available; raw metadata is withheld.

`POST /api/agent/run`, `POST /api/proposals/{proposal_id}/review`, and
`POST /api/campaigns/{campaign_id}/review` are narrowly scoped dashboard mutations.
The redesigned frontend uses read-only `/api/workspace` and explicit review actions. Both require explicit confirmation and a local action header.
Agent requests are idempotent and serialized; existing budget/cache policies are
reused. Approval/rejection is stored additively, preserving original proposal
content/status. There is no publishing endpoint. Browsing performs no paid calls.

Use a single loopback backend process; reviewer identities are not authenticated.
This local demo needs authentication and production job handling before public
deployment. Tests use temporary databases/mock APIs only; no demonstration records
are seeded into the real workspace. See [frontend/README.md](../frontend/README.md)
for architecture, exact commands and limits, and `DASHBOARD_VALIDATION.md` for
validation results.

```bash
.venv/bin/python -m pytest -q
cd frontend
npm test
npm run build
```

## Autonomous hidden-gem discovery and complete campaigns

ATIA can now start an evidence investigation without a destination or campaign
request. The existing Responses API loop lets the model list approved candidate
areas, choose a candidate, inspect identity/coverage evidence and memory, and
optionally request one additional cached-or-live Tavily search. The candidate
catalogue is ordered by evidence availability, **not by inferred hiddenness**.
Geographic clusters, verified entities, and reviewed photo associations remain distinct.

```bash
# Explicitly starts a potentially paid bounded cycle; no destination argument
.venv/bin/atia agent discover
# Read-only inspection; no paid requests
.venv/bin/atia agent discovery-inspect
.venv/bin/atia agent campaigns
```

Decisions are INVESTIGATE, NO_ACTION, CREATE or UPDATE. CREATE/UPDATE must pass
source-quote, verified-identity, reviewed-photo association, image approval/hash,
and campaign-schema checks. A hidden-gem hypothesis requires affirmative sourced
support from two publishers, with contrary evidence retained. This conservative
rule is not proof of underpromotion or a substitute for human judgment.

Complete campaigns include Arabic/English concepts, objectives, audience hypotheses,
messages, creative direction, social captions, channels, a schedule relative to
human-approved launch, activities, KPI measurement plans, uncertainties and sources.
They are stored additively in `agent_campaigns` as PENDING_APPROVAL. Neither this
command nor any tool publishes campaigns. The redesigned Studio reads these expanded campaigns and persists separate human
approval decisions; no campaign is published automatically.

`discovery_contracts.py`, `discovery_tools.py`, `discovery_storage.py`, and
`campaigns.py` extend `src/atia/agents/`; the existing runner, budget reservations,
Tavily provider, moderation policy and SQLite services are reused. Legacy
single-area commands and saved proposals remain available. New tables preserve
prior records. Campaign material fingerprints prevent duplicate drafts; UPDATE
requires an existing campaign and materially changed evidence. Completed cycles
are cached for 24 hours against evidence/configuration changes. Failed or guarded
cycles require an explicit new invocation; they do not resume or retry automatically.

Default limits remain four model requests, three tool calls, one extra Tavily
search, 1,800 output tokens/request and $0.05/run, with a shared $0.25 local ledger
across legacy and discovery runs. These are local controls, not account billing.
Existing `.env` keys stay server-side; no images are uploaded to the LLM.

Optional external scheduling is supported by
`atia agent discover --scheduled --authorize-paid-run`. Only use this command
when deliberately authorizing recurring API spending. No scheduler or recurring
job has been installed. Ordinary dashboard loads never start this cycle.

Validation uses mocked external responses (`tests/test_discovery.py`); see
[DISCOVERY_VALIDATION.md](reports/DISCOVERY_VALIDATION.md) for the one actual live cycle,
its evidence-validation failure, cost, and remaining limitations.

## Flickr intelligence (Phase 1 of the opportunity workflow)

Deterministic, free groundwork for marketing opportunity cards. It reads stored records, checks each
archive photo against the free Flickr API, and caches images. It never calls OpenAI or Tavily, and it
does not run OpenCLIP: it reuses stored results where they exist and leaves the rest empty.

```bash
cp data/atia.sqlite3 data/atia-phase1.sqlite3   # keep the copy beside data/images
atia --db data/atia-phase1.sqlite3 intelligence restore-images   # resumable
atia --db data/atia-phase1.sqlite3 intelligence build            # writes FLICKR_INTELLIGENCE.md
atia --db data/atia-phase1.sqlite3 intelligence inspect --kind regional_experience
```

- `intelligence/licences.py`: every Flickr licence ID has an explicit decision. Non-commercial, no-derivatives,
  all-rights-reserved, uncertain and unknown licences are never campaign-eligible. Archive IDs count only after
  Flickr confirms the current licence. Eligibility is not legal clearance and covers no people or property rights.
- `intelligence/extract.py`, `taxonomy.py`: named places, themes and geography, with the source of each.
  A geotag locates a camera, not a subject. City names and shared city features stay regional context.
- `intelligence/signals.py`: `named_destination`, `regional_experience` and `tourism_theme` signals with evidence,
  images, gaps and a transparent review subset. Signals carry no coverage, demand or overlooked claim.
- `GET /api/intelligence?kind=` serves the latest run read-only for the Discover cards in the next phase.

All tables are additive (`photo_flickr_status`, `photo_image_cache`, `intelligence_runs`, `photo_intelligence`,
`opportunity_signals`). Without them, existing behaviour is unchanged.

## Marketing opportunities (MVP workflow)

Flickr intelligence → opportunity → one bounded investigation → draft → human approval → Calendar.
`config/mvp-opportunities.json` is a hand-picked demo shortlist; each entry must match a real signal.
Regional experiences need no named site, and low engagement is never read as underpromotion.

```bash
atia --db data/atia-phase1.sqlite3 opportunities build
atia --db data/atia-phase1.sqlite3 opportunities find-images          # free, licence-filtered
atia --db data/atia-phase1.sqlite3 opportunities review-image --opportunity qassim-agritourism \
  --photo-id ID --decision accept --reviewer NAME --reason "On topic"
atia --db data/atia-phase1.sqlite3 opportunities generate --opportunity qassim-agritourism --dry-run
atia --db data/atia-phase1.sqlite3 opportunities generate --opportunity qassim-agritourism --confirm-paid
```

Generation makes one OpenAI request through the shared budget ledger and never retries. The model never
picks images: only licence-eligible photos attach, and a draft with none stays text-only. Deterministic
checks reject drafts with uncited claims, figures absent from the evidence, unsupported "hidden gem" or
"underpromoted" language, or missing Arabic. Drafts stay `PENDING_APPROVAL` until a person reviews them.
