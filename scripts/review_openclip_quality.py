"""Read-only score audit. Human observations refer to the ten inspected cached images.

No image inference, network requests, threshold changes, or database writes.
"""
import base64
import hashlib
import html
import json
from pathlib import Path
import sqlite3
import statistics
from atia.config import Settings

OBSERVATIONS = {
 '55354696504': 'Outdoor portrait advertisement with large text overlays; a person, leafless trees, blue sky, and part of a building are visible. This is not a destination landscape. Daylight is plausible; exact time is unknown.',
 '55354696509': 'Indoor portrait advertisement with large text overlays; a person, patterned walls, and a television are visible. Outdoor lighting and weather prompts are inapplicable to the visible scene.',
 '55358677872': 'Advertisement showing two people outdoors against rocky ground, with large text overlays. People and rock formations are visible; the image is portrait-focused rather than a mountain panorama. The pale sky does not establish fog or overcast weather.',
 '55359604186': 'Roadside portrait advertisement with large text overlays. A person, road, buildings, and a street light are visible. This has urban background cues, but is not a destination landscape; exact lighting phase is unclear.',
 '55359765713': 'Seated portrait advertisement with text overlays, a wall, and furniture. A person is clearly visible; the tightly framed scene provides no reliable landscape or outdoor weather evidence.',
 '55359798024': 'Close-up portrait advertisement with large text overlays and a blurred background. A person is visible; setting, weather, and landscape type are not reliably established.',
 '55365818208': 'Portrait advertisement at an outdoor seating area, with text overlays, a person, a tree/greenery, and a drink. Natural ambient light is visible; exact time and weather remain unclear.',
 '55365861304': 'Close-up portrait advertisement inside a vehicle, with large text overlays. A person and car interior are visible; buildings/trees appear through the window. Exterior daylight does not establish capture-clock time or a destination landscape.',
 '55503674714': 'White decorative arched building facade/courtyard under a canopy, with people, motorcycles, and potted plants. Traditional architecture is a plausible visual match. Historical age, cultural significance, precise location, and cloudy weather cannot be verified from appearance alone.',
 '55520699393': 'Aircraft formation against a blue sky with white smoke trails. This is an aviation scene, not a cultural landscape. The trails are not evidence of cloudy or foggy weather; the image appears daylight-lit, without proving a clock time.',
}


def main():
    db_path = Path(Settings.load().db_path)
    before_hash = hashlib.sha256(db_path.read_bytes()).hexdigest()
    c = sqlite3.connect(f'file:{db_path.resolve()}?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    rows = [dict(row) for row in c.execute('''SELECT a.*,p.photo_url,p.captured_at,p.owner_id
        FROM visual_dimension_analyses a JOIN photos p USING(source,photo_id)
        ORDER BY a.photo_id,a.dimension''')]
    # Pin this audit to the inspected snapshot rather than silently mixing versions.
    groups = {}
    for row in rows:
        if row['photo_id'] not in OBSERVATIONS:
            continue
        groups.setdefault(row['photo_id'], {}).setdefault(row['threshold_version'], {})[row['dimension']] = row
    reports = []
    for photo_id, versions in groups.items():
        if len(versions) != 1:
            raise ValueError('Multiple threshold versions: explicitly select the reviewed version before auditing')
        dimensions = next(iter(versions.values()))
        if set(dimensions) != {'environment', 'elements', 'conditions'}:
            raise ValueError('Incomplete dimension set')
        reports.append((photo_id, dimensions))
    assert len(reports) == 10
    thresholds = json.loads(reports[0][1]['environment']['thresholds'])
    env_scores, env_margins, lighting_scores, lighting_margins = [], [], [], []
    for _, dims in reports:
        e = json.loads(dims['environment']['interpretation'])
        conditions = json.loads(dims['conditions']['interpretation'])
        s = json.loads(dims['conditions']['scores'])
        env_scores.append(e['strongest_similarity']);env_margins.append(e['margin'])
        lighting_scores.append(s[conditions['lighting']['strongest_match']])
        lighting_margins.append(conditions['lighting']['margin'])
    summary = f'''# OpenCLIP classification quality review

Visual inspection of all ten cached originals and their existing stored scores. No inference was rerun. Model: ViT-B/32, laion2b_s34b_b79k; OpenCLIP {reports[0][1]['environment']['library_version']}.

## Main finding

Eight images are portrait advertisements with prominent text overlays, one is an architectural courtyard, and one is an aircraft formation. All ten are from the Central-labelled sample; nine distinct Flickr owners do not prevent eight images from sharing an apparent advertisement campaign style. This is a data-quality and sampling problem as well as a classification problem. Geotags/country responses did not establish tourism relevance, image authenticity, or actual capture location. No record has been deleted or reclassified in SQLite.

A previous successful pipeline run established that inference and storage work; it did **not** establish classification quality. The current sample cannot validate performance on deserts, mountains, coasts, forests, sunrise, sunset, or fog because it lacks representative reviewed examples of those conditions.

## Why environment and lighting were uncertain

The score minimum is {thresholds['environment_min']:.2f} for environment and {thresholds['condition_min']:.2f} for conditions; the required top-two margins are {thresholds['environment_margin']:.2f} and {thresholds['lighting_margin']:.2f}.

| Diagnostic | Environment | Lighting |
|---|---:|---:|
| Strongest-score minimum | {min(env_scores):.4f} | {min(lighting_scores):.4f} |
| Strongest-score median | {statistics.median(env_scores):.4f} | {statistics.median(lighting_scores):.4f} |
| Strongest-score maximum | {max(env_scores):.4f} | {max(lighting_scores):.4f} |
| Images below score minimum | {sum(s < thresholds['environment_min'] for s in env_scores)}/10 | {sum(s < thresholds['condition_min'] for s in lighting_scores)}/10 |
| Images below required margin | {sum(m < thresholds['environment_margin'] for m in env_margins)}/10 | {sum(m < thresholds['lighting_margin'] for m in lighting_margins)}/10 |

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
'''
    lines = [summary]
    html_parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>ATIA OpenCLIP quality review</title><style>body{font:16px system-ui;max-width:1100px;margin:36px auto;padding:0 20px;line-height:1.55;color:#18212b}table{border-collapse:collapse;width:100%;margin:14px 0}td,th{border:1px solid #ccd3da;padding:9px;text-align:left}article{border-top:3px solid #718096;margin-top:32px}img{max-width:100%;max-height:600px}pre{white-space:pre-wrap}summary{cursor:pointer}</style><h1>ATIA OpenCLIP image-quality audit</h1><p>Ten cached images inspected; no inference or database changes. Eight portrait advertisements, one courtyard, one aircraft scene. All environment and lighting labels remain uncertain.</p><p>See OPENCLIP_QUALITY_REVIEW.md for the full diagnostic analysis and recommendations. U = uncertain; P = tentative possible match.</p>']
    for photo_id, dims in reports:
        env = dims['environment'];conditions = dims['conditions'];elements = dims['elements']
        es=json.loads(env['scores']);ls=json.loads(conditions['scores']);els=json.loads(elements['scores'])
        ei=json.loads(env['interpretation']);ci=json.loads(conditions['interpretation']);eli=json.loads(elements['interpretation'])
        def ranked(values, labels=None, n=None, status=None):
            keys=sorted(labels or values, key=values.get, reverse=True)
            return '; '.join(f"{key}: {values[key]:.4f} [{status(key) if status else 'U'}]" for key in keys[:n])
        table=[
            ('Environment top 3', ranked(es,n=3), 'No label accepted; strongest '+ei['strongest_match']),
            ('Elements top 5', ranked(els,n=5,status=lambda k:'P' if k in eli['possible_matches'] else 'U'), 'Possible: '+(', '.join(eli['possible_matches']) or 'none')),
            ('Lighting', ranked(ls,('daytime','nighttime','sunrise','sunset')), 'No label accepted'),
            ('Weather', ranked(ls,('cloudy','foggy')), 'No label accepted'),
        ]
        reason=f"Environment: max {ei['strongest_similarity']:.4f} < 0.25; margin {ei['margin']:.4f} {'<' if ei['margin'] < .03 else '>='} 0.03. Lighting: max {ls[ci['lighting']['strongest_match']]:.4f} < 0.25; margin {ci['lighting']['margin']:.4f} {'<' if ci['lighting']['margin'] < .03 else '>='} 0.03."
        url=env['photo_url']
        lines += [f'\n## Photo {photo_id}',f'\n[Flickr photo]({url}) · [Cached original]({env["image_path"]})',f'\n**Visual inspection:** {OBSERVATIONS[photo_id]}',f'\nSaved Flickr capture timestamp: `{env["captured_at"]}` (metadata only; not inferred lighting).','\n| Dimension | Ranked similarities and status | Saved outcome |','|---|---|---|']
        lines += [f'| {name} | {ranking} | {outcome} |' for name,ranking,outcome in table]
        lines += ['\n'+reason]
        content=Path(env['image_path']).read_bytes()
        assert hashlib.sha256(content).hexdigest()==env['image_sha256']
        html_parts += [f'<article><h2>{photo_id}</h2><a href="{html.escape(url)}">Flickr photo</a><p>{html.escape(OBSERVATIONS[photo_id])}</p><details><summary>Cached image preview</summary><img alt="Cached photo {photo_id}" src="data:image/jpeg;base64,{base64.b64encode(content).decode()}"></details><table><tr><th>Dimension</th><th>Ranked similarities</th><th>Outcome</th></tr>']
        html_parts += [f'<tr><td>{html.escape(name)}</td><td>{html.escape(ranking)}</td><td>{html.escape(outcome)}</td></tr>' for name,ranking,outcome in table]
        html_parts += [f'</table><p>{html.escape(reason)}</p><p>Saved capture timestamp (separate metadata): {html.escape(str(env["captured_at"]))}</p></article>']
    lines += ['\n## Preservation and limitations\n', 'The database was opened read-only. Its whole-file SHA-256 is unchanged before/after this audit. All 297 photo rows, 10 legacy analyses, and 30 dimension analyses are preserved. Cached image hashes match the stored evidence. No images were downloaded, no model was loaded, no thresholds/prompts were changed, and no sentiment analysis was started.\n', 'Remaining limitations: an out-of-domain and non-representative sample; unverified geography/authenticity despite user geotags; no reliable broad accuracy estimate; English single-template prompt sensitivity; small/cropped background element misses; no object localization; cultural/historical significance cannot be established visually; ambiguous or inapplicable lighting/weather; and uncalibrated cosine-based abstention. The readable HTML companion includes cached previews; contact details in source advertisements are not transcribed in the report.\n']
    lines += ['\n## Exact stored prompt definitions\n', '| Dimension | Category | Prompt |', '|---|---|---|']
    for dimension, row in reports[0][1].items():
        for label, prompt in json.loads(row['prompts']).items():
            lines.append(f'| {dimension} | {label} | {prompt} |')
    lines += ['\nPrompt version: `'+reports[0][1]['environment']['prompt_version']+'`.',
              '\nThreshold version: `'+reports[0][1]['environment']['threshold_version']+'`.']
    Path('OPENCLIP_QUALITY_REVIEW.md').write_text('\n'.join(lines))
    html_parts.append('</html>')
    Path('data/openclip-quality-review.html').write_text(''.join(html_parts))
    c.close()
    assert hashlib.sha256(db_path.read_bytes()).hexdigest()==before_hash
    print('Created OPENCLIP_QUALITY_REVIEW.md and data/openclip-quality-review.html')
    print('Reviewed 10 cached image hashes; database unchanged; zero inference calls.')


if __name__ == '__main__':
    main()
