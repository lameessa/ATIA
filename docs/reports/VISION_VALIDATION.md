# ATIA Phase 2 validation

Run ID: `ae736baa-00f4-46e6-8951-75b6d10e4c08`

Pretrained model: **ViT-B-32 / laion2b_s34b_b79k**, OpenCLIP 3.3.0, PyTorch 2.15.0, CPU inference. No training or fine-tuning.

Analyzed **10 accessible images** from 10 attempted records. Retrieval failures: 0; inference errors: 0. All selected records are from the live Central-region sample; this is not representative regional sampling.

Total command execution: **149.64 seconds**, including 140.81 seconds for first-time imports/checkpoint download/model and prompt loading. The remaining retrieval, validation, inference, and persistence took 8.83 seconds. Dependency installation is excluded.

| Photo ID | Highest-scoring description | Cosine similarity |
|---|---|---:|
| [photo] | cultural_landmarks | 0.1442 |
| [photo] | other | 0.1293 |
| [photo] | cultural_landmarks | 0.1273 |
| [photo] | other | 0.1274 |
| [photo] | other | 0.1219 |
| [photo] | cultural_landmarks | 0.1280 |
| [photo] | cultural_landmarks | 0.1331 |
| [photo] | other | 0.1130 |
| [photo] | cultural_landmarks | 0.2289 |
| [photo] | cultural_landmarks | 0.1165 |

Scores compare normalized image/text embeddings against eight fixed descriptions. They are not calibrated probabilities, verified category labels, or measures of tourism demand. Low or close scores require caution; the relative top category can be wrong. The `other` category allows a non-tourism comparison but is not a calibrated relevance detector.

All 80 similarity scores and all 30 ranked top-category entries are stored in `visual_analyses`, linked to the original `(source, photo_id)`. Model/checkpoint, prompt text/hash, OpenCLIP version, device, image checksum/path/URL/dimensions, timestamp, and run ID are preserved. Ten successful attempts are recorded in `visual_attempts`.

All **297 original photo rows match their pre-analysis checksum exactly**: 197 historical and 100 live. SQLite integrity and foreign-key checks passed. Each downloaded image checksum was verified against its stored artifact. All 36 automated tests pass. No frontend, autonomous agent, or campaign implementation was added; nothing was pushed.

Full batch JSON with top three matches: `data/vision-report.json`. Downloaded image artifacts: `data/images/`. Model cache: `data/models/`. Pre-analysis database backup: `data/atia-before-vision.sqlite3`. These local data files are ignored by Git.

Run another new batch with `atia analyze --limit 10`. Install optional dependencies using `pip install -r requirements-vision.txt`. See README for implementation details and failure semantics.
