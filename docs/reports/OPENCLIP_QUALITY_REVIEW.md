# OpenCLIP classification quality review

Visual inspection of all ten cached originals and their existing stored scores. No inference was rerun. Model: ViT-B/32, laion2b_s34b_b79k; OpenCLIP 3.3.0.

## Main finding

Eight images are portrait advertisements with prominent text overlays, one is an architectural courtyard, and one is an aircraft formation. All ten are from the Central-labelled sample; nine distinct Flickr owners do not prevent eight images from sharing an apparent advertisement campaign style. This is a data-quality and sampling problem as well as a classification problem. Geotags/country responses did not establish tourism relevance, image authenticity, or actual capture location. No record has been deleted or reclassified in SQLite.

A previous successful pipeline run established that inference and storage work; it did **not** establish classification quality. The current sample cannot validate performance on deserts, mountains, coasts, forests, sunrise, sunset, or fog because it lacks representative reviewed examples of those conditions.

## Why environment and lighting were uncertain

The score minimum is 0.25 for environment and 0.25 for conditions; the required top-two margins are 0.03 and 0.03.

| Diagnostic | Environment | Lighting |
|---|---:|---:|
| Strongest-score minimum | 0.0945 | 0.1466 |
| Strongest-score median | 0.1103 | 0.1756 |
| Strongest-score maximum | 0.2115 | 0.2271 |
| Images below score minimum | 10/10 | 10/10 |
| Images below required margin | 6/10 | 3/10 |

All ten fail the absolute score requirement; six environment and three lighting results also fail the margin requirement. Lowering only the margin would therefore accept **none**. Cultural is the strongest environment description in all ten; daytime is the strongest lighting description in all ten, including indoor/ambiguous portraits. A common top rank is not proof of a correct class. Cosine scores are not calibrated probabilities.

The threshold of 0.25 is an unvalidated heuristic, not a demonstrated operating point. Abstention is appropriate for many out-of-scope scenes here, but does not prove threshold quality: people are visible in nine images and **zero of those nine** receive an accepted `people` match. The courtyard's traditional-architecture score is 0.2557, barely above the cutoff, and is visually plausible. This tiny selected sample is not enough to estimate deployment precision, recall, or a reliable threshold.

## Prompt and preprocessing review

Environment prompts presume a landscape; there is no portrait, advertisement/poster, indoor, aviation, or other/out-of-scope alternative. Cultural and historical descriptions overlap and refer partly to significance/age that appearance cannot establish. Cultural ranking first in unrelated portraits and aircraft is an inappropriate label to accept, not a reason to lower the threshold.

Every condition prompt starts with an outdoor-photo assumption, including for indoor portraits. Only cloudy/foggy weather alternatives exist, so clear sky and unobservable sky are unrepresented. Daytime/nighttime/sunrise/sunset mix broad day phases with transition appearances; sunrise versus sunset is often visually ambiguous. Appearance does not establish capture-clock time.

Element prompts each use one generic sentence (for example, a photograph showing people). These are image-level embedding similarities, not local object detections; multiple objects, small background elements, portraits, and large text overlays can behave differently. The obvious people misses show a concrete weakness. The stock preprocessing implementation uses shortest-edge resize and center crop by default, reducing spatial detail. Text overlay/portrait dominance and crop loss are plausible contributors, **not proven causes**; no counterfactual crop or prompt inference was performed in this audit.

## Recommended next validation steps

1. **Review collection quality before broadening inference.** Add separate, non-destructive eligibility flags for portrait-dominant, text-heavy/promotion-like, indoor, aviation, and landscape scenes. Keep geolocation verification separate from image relevance. Assess OCR/text-area and perceptual-duplicate screening; cross-owner near-duplicates can evade owner caps. Retain rejected observations with reasons rather than deleting evidence.
2. **Build a human-reviewed validation set across all five regions.** Include positive and negative examples for every element, real tourism scenes, hard negatives like these advertisements, indoor scenes, and unknown weather. Keep a separate held-out test set and split by uploader/campaign/near-duplicate group. Measure coverage/abstention as well as precision and recall. The eight advertisements here should become a hard-negative slice, not the entire benchmark.
3. **Evaluate prompt ensembles without training.** Compare short, consistent variants (a landscape photo of a desert; a photo of a person; a photo of a group of people), explicit indoor/non-landscape controls, and environment out-of-scope options. Average normalized text embeddings for each category. Keep historical/cultural interpretations tentative and allow mixed environments where appropriate. Version every prompt change; recommendations here are not claimed improvements until tested.
4. **Separate applicability from lighting/weather.** First assess whether outdoor scene/sky evidence is visible. Compare daylight/artificial indoor light/night/twilight without forcing a timestamp; provide clear-sky and unobservable controls. Preserve visually ambiguous sunrise/sunset as unknown even if either ranks first. Do not treat smoke trails as cloud/fog ground truth.
5. **Calibrate per label on reviewed development data, then evaluate held-out data.** Select thresholds/margins based on an explicit precision/recall and abstention objective. Do not transplant one cosine cutoff across people, forest, weather, and cultural prompts, or lower thresholds until these ten images produce labels. Inspect score separation on positives and negatives; record uncertainty reasons separately for low score, small margin, missing evidence, and out-of-scope scene.
6. **Test spatial/model alternatives only if errors persist.** Compare documented crops or full-frame-preserving preprocessing and, if needed, a pretrained object detector for small elements. These would require new controlled inference and evaluation; none was run or added here.

The model publisher also calls for fixed-taxonomy, task-specific evaluation: [LAION model card](https://huggingface.co/laion/CLIP-ViT-B-32-laion2B-s34B-b79K). Recommendations above are hypotheses to test, not established accuracy gains.

## Reading the per-image results

**U** means uncertain under the saved rule. **P** means accepted only as a tentative possible match, not a verified detection. Environment rows show the top three ranks; elements show the top five; lighting shows all four and weather both scores. Ranking is shown even when no label is accepted. No weather match is accepted in this sample. Human notes are one visual review, not a multi-annotator gold standard or location authentication.


## Photo [photo]

Flickr link and cached original removed from the public copy.

**Visual inspection:** Outdoor portrait advertisement with large text overlays; a person, leafless trees, blue sky, and part of a building are visible. This is not a destination landscape. Daylight is plausible; exact time is unknown.

Saved Flickr capture timestamp: `2026-06-24 05:19:01` (metadata only; not inferred lighting).

| Dimension | Ranked similarities and status | Saved outcome |
|---|---|---|
| Environment top 3 | cultural: 0.1291 [U]; historical: 0.0945 [U]; urban: 0.0921 [U] | No label accepted; strongest cultural |
| Elements top 5 | people: 0.1614 [U]; roads: 0.1553 [U]; water: 0.1413 [U]; traditional_architecture: 0.1365 [U]; sand: 0.1280 [U] | Possible: none |
| Lighting | daytime: 0.1991 [U]; sunset: 0.1407 [U]; sunrise: 0.1371 [U]; nighttime: 0.1338 [U] | No label accepted |
| Weather | cloudy: 0.1305 [U]; foggy: 0.1113 [U] | No label accepted |

Environment: max 0.1291 < 0.25; margin 0.0347 >= 0.03. Lighting: max 0.1991 < 0.25; margin 0.0584 >= 0.03.

## Photo [photo]

Flickr link and cached original removed from the public copy.

**Visual inspection:** Indoor portrait advertisement with large text overlays; a person, patterned walls, and a television are visible. Outdoor lighting and weather prompts are inapplicable to the visible scene.

Saved Flickr capture timestamp: `2026-06-24 05:19:01` (metadata only; not inferred lighting).

| Dimension | Ranked similarities and status | Saved outcome |
|---|---|---|
| Environment top 3 | cultural: 0.0945 [U]; desert: 0.0787 [U]; urban: 0.0733 [U] | No label accepted; strongest cultural |
| Elements top 5 | people: 0.1659 [U]; roads: 0.1317 [U]; water: 0.1229 [U]; traditional_architecture: 0.1166 [U]; sand: 0.1141 [U] | Possible: none |
| Lighting | daytime: 0.1466 [U]; nighttime: 0.1193 [U]; sunset: 0.1104 [U]; sunrise: 0.1064 [U] | No label accepted |
| Weather | cloudy: 0.0886 [U]; foggy: 0.0786 [U] | No label accepted |

Environment: max 0.0945 < 0.25; margin 0.0158 < 0.03. Lighting: max 0.1466 < 0.25; margin 0.0273 < 0.03.

## Photo [photo]

Flickr link and cached original removed from the public copy.

**Visual inspection:** Advertisement showing two people outdoors against rocky ground, with large text overlays. People and rock formations are visible; the image is portrait-focused rather than a mountain panorama. The pale sky does not establish fog or overcast weather.

Saved Flickr capture timestamp: `2026-06-26 22:48:04` (metadata only; not inferred lighting).

| Dimension | Ranked similarities and status | Saved outcome |
|---|---|---|
| Environment top 3 | cultural: 0.1111 [U]; historical: 0.0874 [U]; desert: 0.0815 [U] | No label accepted; strongest cultural |
| Elements top 5 | people: 0.1856 [U]; roads: 0.1436 [U]; rock_formations: 0.1349 [U]; water: 0.1256 [U]; sand: 0.1221 [U] | Possible: none |
| Lighting | daytime: 0.1800 [U]; sunset: 0.1313 [U]; sunrise: 0.1304 [U]; nighttime: 0.1063 [U] | No label accepted |
| Weather | cloudy: 0.1308 [U]; foggy: 0.1061 [U] | No label accepted |

Environment: max 0.1111 < 0.25; margin 0.0237 < 0.03. Lighting: max 0.1800 < 0.25; margin 0.0487 >= 0.03.

## Photo [photo]

Flickr link and cached original removed from the public copy.

**Visual inspection:** Roadside portrait advertisement with large text overlays. A person, road, buildings, and a street light are visible. This has urban background cues, but is not a destination landscape; exact lighting phase is unclear.

Saved Flickr capture timestamp: `2026-06-26 22:42:17` (metadata only; not inferred lighting).

| Dimension | Ranked similarities and status | Saved outcome |
|---|---|---|
| Environment top 3 | cultural: 0.1047 [U]; urban: 0.1026 [U]; historical: 0.0951 [U] | No label accepted; strongest cultural |
| Elements top 5 | people: 0.1723 [U]; roads: 0.1559 [U]; water: 0.1427 [U]; cars: 0.1326 [U]; sand: 0.1292 [U] | Possible: none |
| Lighting | daytime: 0.1712 [U]; nighttime: 0.1526 [U]; sunset: 0.1233 [U]; sunrise: 0.1172 [U] | No label accepted |
| Weather | cloudy: 0.1150 [U]; foggy: 0.0898 [U] | No label accepted |

Environment: max 0.1047 < 0.25; margin 0.0021 < 0.03. Lighting: max 0.1712 < 0.25; margin 0.0186 < 0.03.

## Photo [photo]

Flickr link and cached original removed from the public copy.

**Visual inspection:** Seated portrait advertisement with text overlays, a wall, and furniture. A person is clearly visible; the tightly framed scene provides no reliable landscape or outdoor weather evidence.

Saved Flickr capture timestamp: `2026-06-26 22:41:10` (metadata only; not inferred lighting).

| Dimension | Ranked similarities and status | Saved outcome |
|---|---|---|
| Environment top 3 | cultural: 0.1096 [U]; desert: 0.0914 [U]; urban: 0.0861 [U] | No label accepted; strongest cultural |
| Elements top 5 | people: 0.1656 [U]; roads: 0.1406 [U]; traditional_architecture: 0.1144 [U]; water: 0.1126 [U]; sand: 0.1119 [U] | Possible: none |
| Lighting | daytime: 0.1665 [U]; sunset: 0.1286 [U]; nighttime: 0.1259 [U]; sunrise: 0.1247 [U] | No label accepted |
| Weather | cloudy: 0.1098 [U]; foggy: 0.0864 [U] | No label accepted |

Environment: max 0.1096 < 0.25; margin 0.0182 < 0.03. Lighting: max 0.1665 < 0.25; margin 0.0379 >= 0.03.

## Photo [photo]

Flickr link and cached original removed from the public copy.

**Visual inspection:** Close-up portrait advertisement with large text overlays and a blurred background. A person is visible; setting, weather, and landscape type are not reliably established.

Saved Flickr capture timestamp: `2026-06-26 22:35:44` (metadata only; not inferred lighting).

| Dimension | Ranked similarities and status | Saved outcome |
|---|---|---|
| Environment top 3 | cultural: 0.1173 [U]; historical: 0.1034 [U]; urban: 0.0995 [U] | No label accepted; strongest cultural |
| Elements top 5 | people: 0.1755 [U]; roads: 0.1400 [U]; water: 0.1367 [U]; traditional_architecture: 0.1316 [U]; buildings: 0.1206 [U] | Possible: none |
| Lighting | daytime: 0.1836 [U]; nighttime: 0.1233 [U]; sunset: 0.1189 [U]; sunrise: 0.1127 [U] | No label accepted |
| Weather | cloudy: 0.1345 [U]; foggy: 0.1072 [U] | No label accepted |

Environment: max 0.1173 < 0.25; margin 0.0139 < 0.03. Lighting: max 0.1836 < 0.25; margin 0.0603 >= 0.03.

## Photo [photo]

Flickr link and cached original removed from the public copy.

**Visual inspection:** Portrait advertisement at an outdoor seating area, with text overlays, a person, a tree/greenery, and a drink. Natural ambient light is visible; exact time and weather remain unclear.

Saved Flickr capture timestamp: `2026-06-29 23:19:41` (metadata only; not inferred lighting).

| Dimension | Ranked similarities and status | Saved outcome |
|---|---|---|
| Environment top 3 | cultural: 0.1249 [U]; historical: 0.0893 [U]; urban: 0.0819 [U] | No label accepted; strongest cultural |
| Elements top 5 | people: 0.1558 [U]; roads: 0.1333 [U]; traditional_architecture: 0.1298 [U]; water: 0.1173 [U]; cars: 0.1110 [U] | Possible: none |
| Lighting | daytime: 0.1589 [U]; nighttime: 0.1225 [U]; sunset: 0.1122 [U]; sunrise: 0.1091 [U] | No label accepted |
| Weather | cloudy: 0.1117 [U]; foggy: 0.0804 [U] | No label accepted |

Environment: max 0.1249 < 0.25; margin 0.0355 >= 0.03. Lighting: max 0.1589 < 0.25; margin 0.0364 >= 0.03.

## Photo [photo]

Flickr link and cached original removed from the public copy.

**Visual inspection:** Close-up portrait advertisement inside a vehicle, with large text overlays. A person and car interior are visible; buildings/trees appear through the window. Exterior daylight does not establish capture-clock time or a destination landscape.

Saved Flickr capture timestamp: `2026-06-29 23:21:09` (metadata only; not inferred lighting).

| Dimension | Ranked similarities and status | Saved outcome |
|---|---|---|
| Environment top 3 | cultural: 0.1028 [U]; rural: 0.0828 [U]; urban: 0.0816 [U] | No label accepted; strongest cultural |
| Elements top 5 | people: 0.1755 [U]; roads: 0.1531 [U]; cars: 0.1469 [U]; water: 0.1381 [U]; sand: 0.1173 [U] | Possible: none |
| Lighting | daytime: 0.1704 [U]; sunset: 0.1424 [U]; sunrise: 0.1349 [U]; nighttime: 0.1256 [U] | No label accepted |
| Weather | cloudy: 0.1087 [U]; foggy: 0.0774 [U] | No label accepted |

Environment: max 0.1028 < 0.25; margin 0.0201 < 0.03. Lighting: max 0.1704 < 0.25; margin 0.0280 < 0.03.

## Photo [photo]

Flickr link and cached original removed from the public copy.

**Visual inspection:** White decorative arched building facade/courtyard under a canopy, with people, motorcycles, and potted plants. Traditional architecture is a plausible visual match. Historical age, cultural significance, precise location, and cloudy weather cannot be verified from appearance alone.

Saved Flickr capture timestamp: `2026-09-02 13:32:16` (metadata only; not inferred lighting).

| Dimension | Ranked similarities and status | Saved outcome |
|---|---|---|
| Environment top 3 | cultural: 0.2115 [U]; historical: 0.1805 [U]; urban: 0.1254 [U] | No label accepted; strongest cultural |
| Elements top 5 | traditional_architecture: 0.2557 [P]; buildings: 0.1868 [U]; people: 0.1586 [U]; trees: 0.1231 [U]; cars: 0.1133 [U] | Possible: traditional_architecture |
| Lighting | daytime: 0.2271 [U]; sunrise: 0.1491 [U]; sunset: 0.1412 [U]; nighttime: 0.1338 [U] | No label accepted |
| Weather | cloudy: 0.1894 [U]; foggy: 0.1384 [U] | No label accepted |

Environment: max 0.2115 < 0.25; margin 0.0310 >= 0.03. Lighting: max 0.2271 < 0.25; margin 0.0780 >= 0.03.

## Photo [photo]

Flickr link and cached original removed from the public copy.

**Visual inspection:** Aircraft formation against a blue sky with white smoke trails. This is an aviation scene, not a cultural landscape. The trails are not evidence of cloudy or foggy weather; the image appears daylight-lit, without proving a clock time.

Saved Flickr capture timestamp: `2026-09-10 21:52:46` (metadata only; not inferred lighting).

| Dimension | Ranked similarities and status | Saved outcome |
|---|---|---|
| Environment top 3 | cultural: 0.1031 [U]; mountain: 0.0625 [U]; coastal: 0.0546 [U] | No label accepted; strongest cultural |
| Elements top 5 | people: 0.1508 [U]; water: 0.1368 [U]; cars: 0.1343 [U]; traditional_architecture: 0.1267 [U]; trees: 0.1220 [U] | Possible: none |
| Lighting | daytime: 0.1986 [U]; sunset: 0.1348 [U]; sunrise: 0.1298 [U]; nighttime: 0.0986 [U] | No label accepted |
| Weather | cloudy: 0.1661 [U]; foggy: 0.1461 [U] | No label accepted |

Environment: max 0.1031 < 0.25; margin 0.0406 >= 0.03. Lighting: max 0.1986 < 0.25; margin 0.0638 >= 0.03.

## Preservation and limitations

The database was opened read-only. Its whole-file SHA-256 is unchanged before/after this audit. All 297 photo rows, 10 legacy analyses, and 30 dimension analyses are preserved. Cached image hashes match the stored evidence. No images were downloaded, no model was loaded, no thresholds/prompts were changed, and no sentiment analysis was started.

Remaining limitations: an out-of-domain and non-representative sample; unverified geography/authenticity despite user geotags; no reliable broad accuracy estimate; English single-template prompt sensitivity; small/cropped background element misses; no object localization; cultural/historical significance cannot be established visually; ambiguous or inapplicable lighting/weather; and uncalibrated cosine-based abstention. The readable HTML companion includes cached previews; contact details in source advertisements are not transcribed in the report.


## Exact stored prompt definitions

| Dimension | Category | Prompt |
|---|---|---|
| conditions | daytime | An outdoor photograph taken in daylight during the day. |
| conditions | nighttime | An outdoor photograph taken at night in darkness. |
| conditions | sunrise | An outdoor photograph taken at sunrise with dawn light. |
| conditions | sunset | An outdoor photograph taken at sunset with evening light. |
| conditions | cloudy | An outdoor photograph with overcast cloudy skies. |
| conditions | foggy | An outdoor photograph in fog or mist with low visibility. |
| elements | trees | A photograph showing trees. |
| elements | vegetation | A photograph showing green vegetation, bushes, or plants. |
| elements | cars | A photograph showing cars. |
| elements | roads | A photograph showing roads. |
| elements | buildings | A photograph showing buildings. |
| elements | people | A photograph showing people. |
| elements | water | A photograph showing water. |
| elements | rock_formations | A photograph showing natural rock formations. |
| elements | sand | A photograph showing sand. |
| elements | traditional_architecture | A photograph showing traditional architecture. |
| environment | urban | A photograph of an urban landscape with city streets and modern buildings. |
| environment | desert | A photograph of a desert landscape with dunes and arid sandy plains. |
| environment | mountain | A photograph of a mountain landscape with high rocky peaks. |
| environment | coastal | A photograph of a coastal landscape with beaches and the sea. |
| environment | forest | A photograph of a forest landscape with dense trees and woodland. |
| environment | rural | A photograph of a rural landscape with farmland, fields, and countryside. |
| environment | historical | A photograph of a historical landscape with old buildings and ancient ruins. |
| environment | cultural | A photograph of a cultural landscape with traditional villages and heritage landmarks. |

Prompt version: `038fefb2363382cb0c1199111cb95702f6bb7ba8200d9883a871a8ca3303b4c7`.

Threshold version: `5224a9b8c52b26b95114d7653eca3915257fbc08a3d5330049450aacea17f33f`.