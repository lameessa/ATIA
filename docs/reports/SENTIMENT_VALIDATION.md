# Phase 3: Flickr comments and bilingual sentiment validation

## Initial batch and provenance

All ten selected photos returned successful live comment API responses. Five had comments and five returned empty lists. Selection includes all three currently relevance-approved photo IDs, then curated historical records spread over region labels. **The three approved IDs are themselves historical Afaq records**, not three extra live-source photos. All ten selected records therefore have historical-photo provenance, while the new comment observations have live provenance. No provenance was relabelled.

Historical archive imported: **3,128 comment versions across 136 photos**; 192 successful historical responses and five unavailable responses retained. Live retrieval encountered 68 comments matching the historical versions; no duplicate versions were inserted. Stored observation links: {'afaq_historical': 3128, 'flickr_live': 68}. Archived comments for other photos remain stored but unclassified in this initial batch.

## Results

| Metric | Result |
|---|---:|
| Accessible photos | 10 |
| Observed comments in batch | 68 |
| Comments analyzed | 40 |
| Analyzed Arabic | 0 |
| Analyzed English | 40 |
| Positive | 38 |
| Neutral | 2 |
| Negative | 0 |
| Skipped: uncertain language | 22 |
| Skipped: languages outside Arabic/English policy | 6 |
| Pipeline execution, including first model download | 250.74 seconds |
| Cache replay, no network/inference | 0.07 seconds |
| Retrieval/inference errors in completed run | 0 |

No Arabic comments were detected in this selected batch. This is not a bilingual dataset-quality evaluation: real Arabic sentiment accuracy remains unvalidated. Six explicitly constructed examples (positive/negative/neutral in Arabic and English) passed a separate offline inference sanity check; they were **not inserted as Flickr comments**, are excluded from all dataset counts, and are not an accuracy benchmark.

## Per-photo aggregates

| Photo ID | Observed comments | Analyzed | Positive | Neutral | Negative |
|---|---:|---:|---:|---:|---:|
| [photo] | 6 | 3 | 3 | 0 | 0 |
| [photo] | 0 | 0 | 0 | 0 | 0 |
| [photo] | 16 | 13 | 13 | 0 | 0 |
| [photo] | 9 | 4 | 4 | 0 | 0 |
| [photo] | 28 | 12 | 12 | 0 | 0 |
| [photo] | 0 | 0 | 0 | 0 | 0 |
| [photo] | 0 | 0 | 0 | 0 | 0 |
| [photo] | 0 | 0 | 0 | 0 | 0 |
| [photo] | 0 | 0 | 0 | 0 | 0 |
| [photo] | 9 | 8 | 6 | 2 | 0 |

No explicit destination mappings exist, so destination aggregates are empty rather than invented from region labels. Per-destination aggregation is implemented and tested for explicitly supplied mappings.

## Model and interpretation

Model: `cardiffnlp/twitter-xlm-roberta-base-sentiment`. Pinned commit: `f2f1202b1bdeb07342385c3f807f9c07cd8f5cf8`. CPU inference, three batches. The [model card](https://huggingface.co/cardiffnlp/twitter-xlm-roberta-base-sentiment) lists Arabic and English among its eight sentiment fine-tuning languages. No model training or fine-tuning was performed.

Confidence is an uncalibrated softmax score. Language detection is also heuristic; short praise, names, code-switching, transliteration, and dialects can be uncertain or misidentified. Unsupported/empty/uncertain text is not labelled neutral. The positive-heavy distribution reflects selected Flickr commentary and can praise photo technique or award participation rather than a destination. Tweet-domain sentiment does not establish destination satisfaction, represent tourist opinions, or measure tourism demand. No views or favorites were used.

## Engineering checks and limitations

All 60 automated tests passed. Coverage includes historical/live provenance, empty and failed retrieval, Arabic/English/unsupported/mixed-language handling, duplicate prevention, comment edits including reverting to earlier text, model-version cache invalidation, batching, explicit destination aggregation, and unchanged photo metadata. Canonical SentencePiece and fast-tokenizer inputs match on Arabic/English checks. A missing protobuf tokenizer dependency was fixed; unnecessary background safetensors conversion was disabled. Cached snapshots load offline, avoiding redundant model metadata requests.

All pre-existing photo/OpenCLIP/screening/embedding/review tables match their pre-Phase-3 checksums exactly. SQLite integrity and foreign-key checks passed. The 297 original photo records remain unchanged. The complete cache replay reused all 68 analyzed/skipped decisions and all ten successful retrieval observations; it did not load the model or call Flickr. Use `--refresh-comments` to discover updates. Missing comments in later responses are not assumed deleted.

First-run timing measures pipeline work through saved results. The original completed process waited on an unnecessary Transformers background conversion thread afterward; it was stopped after verifying results were saved, and the loader was fixed to disable that behavior. Subsequent offline model loading and CLI replay exited normally.

Remaining limitations: no independently human-labelled sentiment benchmark; no real Arabic comments in this batch; uncertain-language skips reduce coverage; tweet/Flickr domain mismatch; no aspect-level separation of photo praise from destination opinion; unknown present availability of historical-only evidence; and no destination grouping until mappings are supplied. No agent/frontend was implemented and nothing was pushed.

Files: `src/atia/sentiment/` contains collection, normalization, storage, language detection, pretrained inference, selection, and aggregation. Install `requirements-sentiment.txt`, then run `atia sentiment --limit 10`. Full local reports: `data/sentiment-report.json`, `data/sentiment-final-cache-report.json`, and `data/sentiment-bilingual-smoke.json`.
