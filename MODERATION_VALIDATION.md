# Urgent live-photo quarantine and moderation validation

## Private shortlist update

The user explicitly rejected [photo]. Its `review_status` is **REJECTED**;
its processing state remains quarantined, and it cannot be automatically
reselected, approved, or revived by inference. Its shortlist image copy was removed.
It was not relabelled unsafe merely because the user rejected it.

A targeted official Flickr search provided one additional country-checked Central
candidate, **[photo]**, with clear architectural scenery. Only that new image
was newly scored locally; existing decisions/results were reused. A hash-matched
Codex visual inspection found it relevant and professionally appropriate as a
candidate, without certifying its exact named-attraction identity or reuse rights.
It has **PENDING_REVIEW** status and is not approved or presentation-visible.

The current private shortlist still contains ten images, two per region. Central
has two pending candidates and zero approved. The other nine shortlist selections
and all 61 other pre-existing review records are unchanged. All approvals remain
zero. The new source adds one record beyond the original 100-photo audit below.
Checks: **144 backend tests passed**, SQLite integrity/foreign keys passed, and both
the rejected image and replacement return 404 from presentation-preview routes.
No paid API calls were made. Current proof: `data/research/shortlist-rejection-validation.json`.

The presentation now exposes **197 trusted historical Afaq photographs and zero
live photographs**. The 197 historical photo rows and all historical/source-scoped
analyses, comments, and destination assignments match the pre-change backup.
The frontend design was not changed. Only its development-server filesystem
access policy was tightened to deny data files and secrets.

## Results for the original 100 live photographs

| Outcome | Count |
|---|---:|
| Full local image evaluations completed | 100 / 100 |
| Relevant and safety-screen/visual-inspection passing candidates | 31 |
| Confidently irrelevant | 38 |
| Professionally unsafe solicitation/contact advertisements | 23 |
| Classification uncertain, retained for further review | 31 |
| Removed records and associated active mappings | 38 |
| Live photographs retained privately | 62 |
| Eligible candidates awaiting explicit user approval | 31 |
| Shortlisted for the requested regional review | 10 |
| Approved / visible live photographs | **0 / 0** |

The **23 unsafe images are included in the 38 irrelevant removals**, not an
additional 23 removals. The mutually exclusive final groups are 38 removed,
31 eligible candidates awaiting approval, and 31 uncertain retained images.
Raw storage now contains 259 photos: 197 historical and 62 quarantined live.
The active/presentation dataset contains only 197.

## Method and important limitations

1. Stopped the presentation servers, quarantined every live ID, and installed a
   fail-closed source/approval gate before processing. Missing moderation records
   do not grant visibility. Historical source records remain trusted as requested.
2. Downloaded/validated or reused the actual Flickr images for **all 100** IDs.
   Every image completed local pretrained NSFW evaluation and local OpenCLIP
   relevance evidence. Existing hash-compatible embeddings/scores were reused.
   Automated processing took **128.67 seconds**. No training was performed.
3. Used local pretrained [Falconsai/nsfw_image_detection](https://huggingface.co/Falconsai/nsfw_image_detection),
   revision `96cb0d0342c7afb80cab76ecc58b265fa44da256`, with safetensors and
   `trust_remote_code=False`. Weights are cached under `data/moderation-models`.
   OpenCLIP remains ViT-B/32, `laion2b_s34b_b79k`, with existing versioned prompts.
4. **The NSFW classifier alone was inadequate:** it returned 99 low-risk screens
   and one uncertain result, missing the professional-context problem in contact
   and solicitation advertisements. CLIP alone was also insufficient: initially
   96 relevance decisions remained uncertain and only four were irrelevant with
   matching old visual references. Those outputs were not treated as ground truth.
5. Codex visually inspected **all 100** actual images in private contact sheets,
   assessed relevance and professional content suitability separately, and recorded
   hash-pinned reasons/provenance. This is **assistant visual inspection, not user
   approval or independently collected human ground truth**. The inspection used
   the current Codex session; automated image inference ran locally. No external
   moderation-API image upload or paid generation request was performed.
6. Only clear visual rejections were retired. Portraits were rejected for scene
   usefulness, not gender, religious identity, or clothing. Sexual/contact and
   relationship-solicitation advertisements were judged unsuitable for this
   professional tourism platform; no claim of illegality or identity was made.
   Aircraft/event scenes, landmark-backdrop portraits, partial scenery, and other
   ambiguous cases remain private. Similarity/softmax scores are not calibrated
   tourism relevance, demand, or professional safety probabilities.

Local NSFW detection does not comprehensively cover violence, hate, consent,
licensing, or Saudi cultural context. Visual inspection can miss details, too.
Consequently, even all 31 candidate passes still require **your** review of the
exact image and context before release. Geographic region assignment uses the
existing coordinate-zone scheme where the original region was absent; it does
not verify an attraction name or authenticate user-supplied geotags.

An attempted external OpenAI moderation upload was rejected by automatic approval
review because specific permission to send potentially sensitive personal images
to that service had not been given. The rejected command did not execute. The
workflow was changed to local model inference instead. OpenAI's existing paid
agent-request ledger is unchanged. **Additional application API cost: $0.**

## Private approval shortlist

Open `data/private-review/index.html` locally. This file is not served by the
dashboard. Its ten candidate images and `manifest.json` are private, unapproved
review artifacts. They are shortlisted candidates, not certified safe content or
verified named attractions. No region has a candidate shortfall in this run.

| Region | Eligible candidates | Shortlisted Flickr IDs | Approved |
|---|---:|---|---:|
| North | 5 | [photo], [photo] | 0 |
| South | 5 | [photo], [photo] | 0 |
| East | 9 | [photo], [photo] | 0 |
| West | 10 | [photo], [photo] | 0 |
| Central | 2 | [photo], [photo] | 0 |

After personally inspecting an image, approve it explicitly (this example is a
command for the user, **not an approval already executed**):

```bash
.venv/bin/atia moderation review PHOTO_ID --approve \
  --reviewer "Your name" --reason "I checked this exact image and its tourism/professional suitability" --confirm
```

No `--approve` invocation was performed on the real database. The command requires
both dimensions to pass, a matching visual inspection, the cached reviewed image
hash, and an explicit named review. It caps approvals at two per region. Omitting
`--approve` records a hold/rejection rather than publishing an image. The private
queue has no buttons that silently approve or invoke paid services.

## Recurrence prevention and deletion

- New `flickr_live` inserts enter quarantine atomically through `PhotoStore.save`.
  A missing or incomplete moderation result fails closed even for direct legacy
  rows. The collector checks the removal tombstone before saving an ID again.
- New `photo_moderation` records hold independent relevance/safety assessments,
  model and prompt provenance, explanations, image hashes, and user-review state.
- Presentation SQLite connections shadow `photos` with a read-only filtered TEMP
  view. `active_photos` and `active_destination_photo_assignments` expose curated
  or explicitly approved data only. Dashboard clusters are projected from approved
  records; old private geographic snapshots do not leak their original photo IDs.
- Direct live-image routes deny unapproved and removed IDs. After an approval,
  only the hash-checked cached pixels are served, with `Cache-Control: no-store`;
  a new/changed remote Flickr image is not substituted for what the user reviewed.
- Agent context, memory, saved run/proposal presentation, research and new decision
  validation exclude blocked photo evidence. Quarantine-only areas cannot start
  an agent run; proposals with blocked evidence cannot be approved.
- Retirement requires a clear, hash-matched visual rejection. It deletes live
  photo rows and dependent live visual analyses, review members, comments,
  sentiment and destination assignments while keeping foreign keys enabled.
  Shared historical image assets and historical rows are protected.
- Deleted **50 cached/derived files**, including the retired image caches, old
  embedded review previews and temporary contact sheets. Uncertain originals and
  the safe-candidate private queue remain private. `photo_removal_audit` contains
  only Flickr ID, removal reason (including both decisions), and timestamp.
- Old geographic snapshots and non-image recovery backups remain private and are
  never used as approved image galleries. They do not override quarantine gates.
- Private review is a CLI/filesystem workflow, separate from public-facing routes.
  Vite denies filesystem access to `data/` and `.env`; no private review endpoint
  or moderation approval tool was added to the autonomous agent.

## Validation

- **142 backend tests passed**, including eight moderation tests for fail-closed
  visibility, no automatic release, ambiguous-retention protection, minimal
  tombstones, cache deletion, recollection blocking, historical preservation,
  blocked agent context, private queue exports and exact approved-pixel delivery.
- **Seven frontend tests passed; TypeScript/Vite build passed.** Design unchanged.
- All **100 original live IDs** were checked against the presentation APIs; none
  appeared in photos, overview, areas/details, research, runs, proposals or jobs.
  All 100 direct live-preview requests returned 404.
- All 197 historical photo rows and historical/source-scoped child tables match
  the pre-moderation backup. The active live-photo and active live-assignment
  counts are zero. Retired IDs cannot be collected again.
- SQLite integrity: **ok**; foreign-key violations: **0**. Retained cached assets
  are referenced; retired caches and temporary contact sheets are absent.
- Actual loopback frontend/proxy checks returned only 197 historical photos;
  an unapproved preview returned 404, and private-review/`.env` filesystem routes
  returned 403. Refresh any already-open dashboard tab to discard its old DOM.

Commands, from the project root:

```bash
.venv/bin/python -m pip install -r requirements-moderation.txt
.venv/bin/atia moderation status
.venv/bin/atia moderation evaluate        # local evaluation, all remaining live; cached results reused
.venv/bin/atia moderation queue
.venv/bin/atia moderation import-inspections PATH_TO_HASH_PINNED_INSPECTIONS.json
.venv/bin/atia moderation retire          # clear visual rejections only; ambiguous records retained
.venv/bin/python -m pytest -q
```

Machine-readable proof: `data/research/moderation-validation.json`. Original
automated-stage counts: `live-moderation-evaluation.json`. Retirement manifest:
`live-retirement.json`. Human-review shortlist: `data/private-review/manifest.json`.
No new phase, model training, campaign publishing or GitHub push.
