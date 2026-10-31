# Tourism relevance screening: small validation

Sample: `regional-59fdf9a7ed13bc6f`. Reviewer: `assistant-visual-review-v1`; review types: assistant_visual_inspection_not_independent_human_ground_truth.

Model/checkpoint and runtime provenance: `{"embedding": "L2-normalized-float32", "libraries": {"Pillow": "12.3.0", "open_clip_torch": "3.3.0", "torch": "2.15.0", "torchvision": "0.29.2"}, "model_name": "ViT-B-32", "preprocessing": "openclip-default-eval-v1", "pretrained": "laion2b_s34b_b79k"}`.

**These are assistant visual-review labels, not independent human ground truth.** Labels were recorded before new predictions were generated. A person should confirm/revise them using the preview report. No thresholds were fitted or changed after evaluation. This is a small stratified development set, not a representative population benchmark or a held-out test.

The regional slice contains three accessible images per region, selected before prediction using a fixed seed with historical/live coverage where available. The separate prior-audit slice is a deliberately enriched hard-negative regression set; never pool it into population prevalence estimates. Historical region labels are retained provenance, not independently verified geographic truth.

| Stratum | Relevant | Irrelevant | Uncertain | Decisive disagreements | Abstentions on clear review labels |
|---|---:|---:|---:|---:|---:|
| audit_regression | 0 | 3 | 7 | 0 | 7 |
| regional | 3 | 1 | 11 | 0 | 9 |

| Region (regional slice only) | Relevant | Irrelevant | Uncertain |
|---|---:|---:|---:|
| North | 0 | 0 | 3 |
| South | 1 | 0 | 2 |
| East | 0 | 1 | 2 |
| West | 1 | 0 | 2 |
| Central | 1 | 0 | 2 |

## Per-image review

| Region / stratum | Photo | Review label | Prediction | Destination / irrelevant scores | Visual review reason |
|---|---|---|---|---|---|
| North / regional | [[photo]]([Flickr link removed] | relevant | uncertain | 0.2023 / 0.1869 | Rock formation and desert campsite scenery visible through a tent opening; potential natural-attraction imagery despite foreground camping gear. |
| North / regional | [[photo]]([Flickr link removed] | relevant | uncertain | 0.2483 / 0.1415 | Wide desert scene with sandstone rocks and sky; useful landscape, without inferring a precise capture time. |
| North / regional | [[photo]]([Flickr link removed] | relevant | uncertain | 0.2029 / 0.1670 | Wide reedbed and birds under clouds; potential nature/wetland landscape, not a product or portrait. |
| South / regional | [[photo]]([Flickr link removed] | uncertain | uncertain | 0.1869 / 0.1655 | Night-time close-up of a lamp and tree; may illustrate a public place but destination context is insufficient. |
| South / regional | [[photo]]([Flickr link removed] | relevant | relevant | 0.2638 / 0.1461 | Wide mountainous landscape with vegetation and dramatic sky; a useful natural-attraction view. |
| South / regional | [[photo]]([Flickr link removed] | relevant | uncertain | 0.2477 / 0.1304 | Water pool, rocks, and vegetation form a clear natural landscape. |
| East / regional | [[photo]]([Flickr link removed] | irrelevant | irrelevant | 0.1495 / 0.2814 | Portrait dominated by promotional text and contact overlay; not destination-focused imagery. |
| East / regional | [[photo]](#) | pending | unavailable | not scored | Photo sizes inaccessible; current availability is unknown. |
| East / regional | [[photo]]([Flickr link removed] | uncertain | uncertain | 0.2220 / 0.1386 | Leafy residential walkway; potential public-space context, but access and destination relevance are unclear. |
| East / regional | [[photo]]([Flickr link removed] | relevant | uncertain | 0.2307 / 0.1579 | Wide palm-grove landscape and sky; potential rural/natural destination imagery. |
| West / regional | [[photo]]([Flickr link removed] | irrelevant | uncertain | 0.1381 / 0.1766 | Posed portrait with a scooter and fragmentary background; person is the focus rather than a destination. |
| West / regional | [[photo]]([Flickr link removed] | relevant | relevant | 0.2779 / 0.1375 | Old earthen-building ruins with an architectural view; potential heritage imagery, without verifying age or location. |
| West / regional | [[photo]]([Flickr link removed] | relevant | uncertain | 0.2208 / 0.1571 | Wide architectural view of a mirrored building reflecting rock formations, with small people; destination context dominates. |
| Central / regional | [[photo]]([Flickr link removed] | relevant | uncertain | 0.1972 / 0.1300 | Waterside scene with birds, cliff, and waterfall; potential nature/public-space imagery. |
| Central / regional | [[photo]]([Flickr link removed] | relevant | uncertain | 0.2173 / 0.1983 | Night-time urban infrastructure and decorative lighting with a broad scene; potential urban/public-space imagery. |
| Central / regional | [[photo]]([Flickr link removed] | relevant | relevant | 0.2647 / 0.1325 | Wide traditional architectural interior with columns and roof structure; useful heritage/architecture imagery. |
| Central / audit_regression | [[photo]]([Flickr link removed] | irrelevant | irrelevant | 0.1388 / 0.2744 | Previously inspected portrait advertisement with large promotional/contact overlays; not destination-focused imagery. |
| Central / audit_regression | [[photo]]([Flickr link removed] | irrelevant | uncertain | 0.1228 / 0.2166 | Previously inspected portrait advertisement with large promotional/contact overlays; not destination-focused imagery. |
| Central / audit_regression | [[photo]]([Flickr link removed] | irrelevant | uncertain | 0.1321 / 0.2081 | Previously inspected portrait advertisement with large promotional/contact overlays; not destination-focused imagery. |
| Central / audit_regression | [[photo]]([Flickr link removed] | irrelevant | uncertain | 0.1323 / 0.2463 | Previously inspected portrait advertisement with large promotional/contact overlays; not destination-focused imagery. |
| Central / audit_regression | [[photo]]([Flickr link removed] | irrelevant | uncertain | 0.1141 / 0.2128 | Previously inspected portrait advertisement with large promotional/contact overlays; not destination-focused imagery. |
| Central / audit_regression | [[photo]]([Flickr link removed] | irrelevant | irrelevant | 0.1298 / 0.2813 | Previously inspected portrait advertisement with large promotional/contact overlays; not destination-focused imagery. |
| Central / audit_regression | [[photo]]([Flickr link removed] | irrelevant | uncertain | 0.1194 / 0.2440 | Previously inspected portrait advertisement with large promotional/contact overlays; not destination-focused imagery. |
| Central / audit_regression | [[photo]]([Flickr link removed] | irrelevant | irrelevant | 0.1324 / 0.2509 | Previously inspected portrait advertisement with large promotional/contact overlays; not destination-focused imagery. |
| Central / audit_regression | [[photo]]([Flickr link removed] | relevant | uncertain | 0.2342 / 0.1547 | Decorative arched building courtyard with people and plants; architecture is the dominant destination context. |
| Central / audit_regression | [[photo]]([Flickr link removed] | irrelevant | uncertain | 0.1325 / 0.2220 | Aircraft against sky without a destination view. |

## Gated detailed-classification outputs

Only model-relevant images receive these new outputs. Compare them with the pre-inference review reasons above; no independent human accuracy score is claimed.

| Photo | Strongest environment / similarity | Accepted environment | Possible elements | Lighting |
|---|---|---|---|---|
| [photo] | mountain / 0.2617 | mountain | none accepted | uncertain |
| [photo] | historical / 0.2925 | historical | none accepted | uncertain |
| [photo] | historical / 0.2609 | historical | traditional_architecture | uncertain |

For this development sample, the mountain and historical-style architecture matches are qualitatively consistent with the review notes. Historical is a visual resemblance, not verified age or significance. The ruins image visibly contains buildings but receives no accepted elements, illustrating remaining element-recall limitations. No lighting label is forced. These observations are not proof of an accuracy gain from the new prompts; the earlier sample and prompts are not a controlled paired benchmark.

## Confusion matrices and mistakes

Rows = review label; columns = model prediction. Uncertain predictions are abstentions, not automatic exclusions. A decisive prediction on a review-uncertain image is an overcommitment needing review.
```json
{
  "audit_regression": {
    "reviewed_predictions": 10,
    "confusion": {
      "relevant": {
        "relevant": 0,
        "irrelevant": 0,
        "uncertain": 1
      },
      "irrelevant": {
        "relevant": 0,
        "irrelevant": 3,
        "uncertain": 6
      },
      "uncertain": {
        "relevant": 0,
        "irrelevant": 0,
        "uncertain": 0
      }
    },
    "decisive_disagreements": [],
    "abstentions_on_decisive_labels": [
      {
        "photo_id": "[photo]",
        "region": "Central",
        "review": "irrelevant",
        "prediction": "uncertain"
      },
      {
        "photo_id": "[photo]",
        "region": "Central",
        "review": "irrelevant",
        "prediction": "uncertain"
      },
      {
        "photo_id": "[photo]",
        "region": "Central",
        "review": "irrelevant",
        "prediction": "uncertain"
      },
      {
        "photo_id": "[photo]",
        "region": "Central",
        "review": "irrelevant",
        "prediction": "uncertain"
      },
      {
        "photo_id": "[photo]",
        "region": "Central",
        "review": "irrelevant",
        "prediction": "uncertain"
      },
      {
        "photo_id": "[photo]",
        "region": "Central",
        "review": "relevant",
        "prediction": "uncertain"
      },
      {
        "photo_id": "[photo]",
        "region": "Central",
        "review": "irrelevant",
        "prediction": "uncertain"
      }
    ]
  },
  "regional": {
    "reviewed_predictions": 15,
    "confusion": {
      "relevant": {
        "relevant": 3,
        "irrelevant": 0,
        "uncertain": 8
      },
      "irrelevant": {
        "relevant": 0,
        "irrelevant": 1,
        "uncertain": 1
      },
      "uncertain": {
        "relevant": 0,
        "irrelevant": 0,
        "uncertain": 2
      }
    },
    "decisive_disagreements": [],
    "abstentions_on_decisive_labels": [
      {
        "photo_id": "[photo]",
        "region": "North",
        "review": "relevant",
        "prediction": "uncertain"
      },
      {
        "photo_id": "[photo]",
        "region": "North",
        "review": "relevant",
        "prediction": "uncertain"
      },
      {
        "photo_id": "[photo]",
        "region": "North",
        "review": "relevant",
        "prediction": "uncertain"
      },
      {
        "photo_id": "[photo]",
        "region": "South",
        "review": "relevant",
        "prediction": "uncertain"
      },
      {
        "photo_id": "[photo]",
        "region": "East",
        "review": "relevant",
        "prediction": "uncertain"
      },
      {
        "photo_id": "[photo]",
        "region": "West",
        "review": "irrelevant",
        "prediction": "uncertain"
      },
      {
        "photo_id": "[photo]",
        "region": "West",
        "review": "relevant",
        "prediction": "uncertain"
      },
      {
        "photo_id": "[photo]",
        "region": "Central",
        "review": "relevant",
        "prediction": "uncertain"
      },
      {
        "photo_id": "[photo]",
        "region": "Central",
        "review": "relevant",
        "prediction": "uncertain"
      }
    ]
  }
}
```

## Fixed policy and limitations
```json
{
  "minimum": 0.25,
  "relevance_margin": 0.03,
  "detail_minimum": 0.25,
  "detail_margin": 0.03,
  "contrast_margin": 0.03
}
```

Scores are cosine similarities, not calibrated probabilities. An irrelevant decision marks the image excluded from destination analysis without deleting the photo or earlier analyses. Uncertain decisions remain in a needs-review queue; detailed destination classification is deferred. Relevant images alone receive the new contrastive environment/element/condition analysis. Capture timestamps remain untouched.

The model still has prompt sensitivity, portrait/advertisement overlap, uncertain destination context, small-element limitations, and visually ambiguous lighting. Geographic balance alone does not establish semantic representativeness, tourism demand, image authenticity, or precise location. Larger independently human-labelled development and held-out sets are required before threshold calibration or accuracy claims.

## Execution and preservation verification

The full screening/classification pass took **4.44 seconds** (model weights already cached), encoding 25 snapshots in seven batches. Replay returned 25 cached assessments in less than 0.01 seconds with zero image batches. One unavailable preparation candidate was retained and replaced; no deletion was inferred. All 25 previews and their image checksums were verified.

All **297 photo records, 10 legacy analyses, 30 earlier dimension analyses, and 20 earlier attempts** match their before-run checksums exactly. New gated detail rows: nine (three dimensions for each of three eligible images). All policies and prompt hashes match the pre-review registration. SQLite integrity and foreign keys passed. **54 automated tests passed**. No sentiment analysis, agent, training, fine-tuning, or frontend was implemented, and nothing was pushed.

Interactive local previews: `data/relevance-review/previews.html` (private, not published). Full evaluation: `data/relevance-review/evaluation.json` (private, not published).
