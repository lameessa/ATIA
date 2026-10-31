# Three-dimension OpenCLIP validation

Model: ViT-B-32 / laion2b_s34b_b79k. Ten accessible live Central-region photographs encoded in 3 image batches (4, 4, 2). All 24 text prompts encoded once.

Execution: **10.89 seconds**. Retrieval errors: 0; inference errors: 0.
Cache replay: **0.01 seconds**, 10 cache hits, zero image batches, no model loading or network retrieval.

| Photo ID | Strongest environment | Accepted environment | Possible elements | Lighting | Weather |
|---|---|---|---|---|---|
| [photo] | cultural | uncertain | uncertain | uncertain | uncertain |
| [photo] | cultural | uncertain | uncertain | uncertain | uncertain |
| [photo] | cultural | uncertain | uncertain | uncertain | uncertain |
| [photo] | cultural | uncertain | uncertain | uncertain | uncertain |
| [photo] | cultural | uncertain | uncertain | uncertain | uncertain |
| [photo] | cultural | uncertain | uncertain | uncertain | uncertain |
| [photo] | cultural | uncertain | uncertain | uncertain | uncertain |
| [photo] | cultural | uncertain | uncertain | uncertain | uncertain |
| [photo] | cultural | uncertain | traditional_architecture | uncertain | uncertain |
| [photo] | cultural | uncertain | uncertain | uncertain | uncertain |

Threshold configuration:
```json
{
  "environment_min": 0.25,
  "environment_margin": 0.03,
  "element_min": 0.25,
  "condition_min": 0.25,
  "lighting_margin": 0.03
}
```

All thresholds are uncalibrated heuristics. Matches are possible image/text correspondences, not probabilities or established detections. Low scores and small environment/lighting margins remain uncertain. Missing element matches do not imply absence. Sunrise/sunset appearances do not establish clock times. This sample is not representative across Saudi regions.

SQLite holds 30 separate dimension rows and 240 cosine scores, including model/checkpoint/library version, dimension-specific prompts, prompt and threshold hashes, thresholds, image provenance, and interpretations. All 297 original photo rows (including Flickr capture timestamps) and all 10 legacy analyses match their before-run checksums exactly. Integrity and foreign-key checks passed.

47 automated tests passed, including multi-element matches, conflicting lighting, uncertainty, invalid thresholds, atomic persistence, 4/4/2 batching, cache reuse, and threshold-only reinterpretation without inference. No training or autonomous agent was implemented.

Local reports: `data/dimensions-report.json` and `data/dimensions-cache-report.json`. Definitions: `src/atia/vision/dimensions.py`; editable thresholds: `config/vision_thresholds.json`. See README for CLI usage and cache semantics.
