"""Review labels and a portable evaluation report; no threshold fitting."""
import base64
from collections import Counter
import html
import json
from pathlib import Path
from atia.models import utc_now
from atia.vision.screen_storage import ScreeningStore
from atia.vision.relevance_prompts import POLICY,POLICY_VERSION,SCREEN_VERSION,DETAIL_VERSION


def import_labels(store,sample_id,path):
    storage=ScreeningStore(store);members={r['photo_id']:r for r in storage.members(sample_id) if r['status']=='available'}
    document=json.loads(Path(path).read_text())
    reviewer=document['reviewer'];review_type=document['review_type']
    if not isinstance(reviewer,str) or not reviewer.strip() or not isinstance(review_type,str) or not review_type.strip():
        raise ValueError('Explicit reviewer and review_type required')
    validated=[];seen=set()
    for item in document['labels']:
        photo_id=str(item['photo_id'])
        if photo_id in seen:raise ValueError('Duplicate label in review file')
        seen.add(photo_id)
        if item['label'] not in {'relevant','irrelevant','uncertain'} or not item.get('reason'):
            raise ValueError('Valid label and review reason required')
        record=members.get(photo_id)
        if record is None or item.get('image_sha256')!=record['image_sha256']:
            raise ValueError('Review must reference the exact sampled image checksum')
        old=store.connection.execute('SELECT label,reason FROM visual_review_labels WHERE sample_id=? AND source=? AND photo_id=? AND reviewer=?',
                                    (sample_id,record['source'],photo_id,reviewer)).fetchone()
        if old and (old['label']!=item['label'] or old['reason']!=item['reason']):
            raise ValueError('Existing review is immutable; use a new reviewer identifier for revisions')
        validated.append((sample_id,record['source'],photo_id,record['image_sha256'],item['label'],reviewer,review_type,item['reason'],utc_now()))
    with store.connection:
        store.connection.executemany('INSERT OR IGNORE INTO visual_review_labels VALUES(?,?,?,?,?,?,?,?,?)',validated)
    return {'reviewer':reviewer,'review_type':review_type,'labels':len(validated)}


def evaluate_rows(rows):
    labels=('relevant','irrelevant','uncertain')
    confusion={actual:{predicted:0 for predicted in labels} for actual in labels}
    mistakes=[];abstentions=[]
    for row in rows:
        actual,predicted=row.get('review_label'),row.get('decision')
        if actual is None or predicted is None:continue
        confusion[actual][predicted]+=1
        if actual!=predicted:
            item={'photo_id':row['photo_id'],'region':row['region'],'review':actual,'prediction':predicted}
            if predicted=='uncertain':abstentions.append(item)
            else:mistakes.append(item)
    return {'reviewed_predictions':sum(sum(row.values()) for row in confusion.values()),'confusion':confusion,
            'decisive_disagreements':mistakes,'abstentions_on_decisive_labels':abstentions}


def export_review(store,sample_id,reviewer,output_dir='data/relevance-review'):
    storage=ScreeningStore(store);directory=Path(output_dir);directory.mkdir(parents=True,exist_ok=True)
    rows=[]
    for member in storage.members(sample_id):
        label=store.connection.execute('SELECT * FROM visual_review_labels WHERE sample_id=? AND source=? AND photo_id=? AND reviewer=?',
                     (sample_id,member['source'],member['photo_id'],reviewer)).fetchone()
        prediction=store.connection.execute('''SELECT * FROM tourism_relevance WHERE source=? AND photo_id=? AND image_sha256=?
                    AND screen_version=? AND detail_version=? AND policy_version=? ORDER BY analyzed_at DESC LIMIT 1''',
                    (member['source'],member['photo_id'],member['image_sha256'],SCREEN_VERSION,DETAIL_VERSION,POLICY_VERSION)).fetchone()
        row={**member,'review_label':label['label'] if label else None,'review_reason':label['reason'] if label else None,
             'reviewer':reviewer,'review_type':label['review_type'] if label else None,'model_spec':json.loads(prediction['model_spec']) if prediction else None,'decision':prediction['decision'] if prediction else None,
             'screen':json.loads(prediction['screen_result']) if prediction else None,
             'details':json.loads(prediction['detail_result']) if prediction and prediction['detail_result'] else None}
        rows.append(row)
    report={'sample_id':sample_id,'policy':POLICY,'policy_version':POLICY_VERSION,'screen_version':SCREEN_VERSION,'detail_version':DETAIL_VERSION,
            'model_spec':next((r['model_spec'] for r in rows if r['model_spec']),None),'reviewer':reviewer,'review_types':sorted({r['review_type'] for r in rows if r['review_type']}),
            'counts':dict(Counter(r['decision'] for r in rows if r['decision'])),'errors':[{'photo_id':r['photo_id'],'error':r['error']} for r in rows if r['status']!='available'],
            'strata':{stratum:{'predictions':dict(Counter(r['decision'] for r in rows if r['stratum']==stratum and r['decision'])),
                            'evaluation':evaluate_rows([r for r in rows if r['stratum']==stratum])} for stratum in sorted({r['stratum'] for r in rows})},
            'by_region':{region:dict(Counter(r['decision'] for r in rows if r['stratum']=='regional' and r['region']==region and r['decision']))
                         for region in ('North','South','East','West','Central')},'rows':rows}
    (directory/'evaluation.json').write_text(json.dumps(report,indent=2))
    lines=['# Tourism relevance screening: small validation','',f'Sample: `{sample_id}`. Reviewer: `{reviewer}`; review types: '+', '.join(report['review_types'])+'.',
           '', 'Model/checkpoint and runtime provenance: `'+json.dumps(report['model_spec'],sort_keys=True)+'`.', '', '**These are assistant visual-review labels, not independent human ground truth.** Labels were recorded before new predictions were generated. A person should confirm/revise them using the preview report. No thresholds were fitted or changed after evaluation. This is a small stratified development set, not a representative population benchmark or a held-out test.',
           '', 'The regional slice contains three accessible images per region, selected before prediction using a fixed seed with historical/live coverage where available. The separate prior-audit slice is a deliberately enriched hard-negative regression set; never pool it into population prevalence estimates. Historical region labels are retained provenance, not independently verified geographic truth.',
           '', '| Stratum | Relevant | Irrelevant | Uncertain | Decisive disagreements | Abstentions on clear review labels |','|---|---:|---:|---:|---:|---:|']
    for stratum,values in report['strata'].items():
        counts=values['predictions'];ev=values['evaluation']
        lines.append(f"| {stratum} | {counts.get('relevant',0)} | {counts.get('irrelevant',0)} | {counts.get('uncertain',0)} | {len(ev['decisive_disagreements'])} | {len(ev['abstentions_on_decisive_labels'])} |")
    lines += ['','| Region (regional slice only) | Relevant | Irrelevant | Uncertain |','|---|---:|---:|---:|']
    for region,counts in report['by_region'].items():lines.append(f"| {region} | {counts.get('relevant',0)} | {counts.get('irrelevant',0)} | {counts.get('uncertain',0)} |")
    lines += ['','## Per-image review','', '| Region / stratum | Photo | Review label | Prediction | Destination / irrelevant scores | Visual review reason |','|---|---|---|---|---|---|']
    parts=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>ATIA relevance review</title><style>body{font:16px system-ui;max-width:1100px;margin:35px auto;padding:0 18px;line-height:1.5}article{border-top:2px solid #999;margin-top:25px}img{max-width:100%;max-height:450px}pre{white-space:pre-wrap}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #ccc}</style><h1>ATIA relevance validation</h1><p>Assistant visual-review annotations, not independent human ground truth. Labels were recorded before prediction. Thresholds remain frozen. Regional sample and prior-audit regression set are separate.</p>']
    for row in rows:
        screen=row['screen'];pair=f"{screen['destination_score']:.4f} / {screen['irrelevant_score']:.4f}" if screen else 'not scored'
        reason=row['review_reason'] or row['error'] or 'awaiting review'
        lines.append(f"| {row['region']} / {row['stratum']} | [{row['photo_id']}]({row['photo_url'] or '#'}) | {row['review_label'] or 'pending'} | {row['decision'] or row['status']} | {pair} | {reason.replace('|','/')} |")
        parts += [f"<article><h2>{row['region']} / {row['stratum']} — {row['photo_id']}</h2><p><a href='{html.escape(row['photo_url'] or '#')}'>Flickr URL</a></p><p>Review: {row['review_label']} · Prediction: {row['decision'] or row['status']} · Scores: {pair}</p><p>{html.escape(reason)}</p>"]
        if row['status']=='available':
            import hashlib
            content=Path(row['image_path']).read_bytes()
            assert hashlib.sha256(content).hexdigest()==row['image_sha256']
            parts.append(f"<details><summary>Image preview</summary><img alt='Sample photo {row['photo_id']}' src='data:image/jpeg;base64,{base64.b64encode(content).decode()}'></details>")
        if screen:parts.append('<details><summary>Stored relevance scores</summary><pre>'+html.escape(json.dumps(screen,indent=2))+'</pre></details>')
        if row['details']:parts.append('<details><summary>Gated destination classification</summary><pre>'+html.escape(json.dumps(row['details'],indent=2))+'</pre></details>')
        parts.append('</article>')
    lines += ['','## Gated detailed-classification outputs','',
              'Only model-relevant images receive these new outputs. Compare them with the pre-inference review reasons above; no independent human accuracy score is claimed.',
              '', '| Photo | Strongest environment / similarity | Accepted environment | Possible elements | Lighting |', '|---|---|---|---|---|']
    for row in rows:
        if not row['details']:continue
        detail=row['details'];environment=detail['environment'];best=environment['strongest_match']
        lines.append(f"| {row['photo_id']} | {best} / {environment['scores'][best]:.4f} | {environment['label'] or 'uncertain'} | {', '.join(detail['elements']['possible_matches']) or 'none accepted'} | {detail['conditions']['lighting_label'] or 'uncertain'} |")
    lines += ['', 'For this development sample, the mountain and historical-style architecture matches are qualitatively consistent with the review notes. Historical is a visual resemblance, not verified age or significance. The ruins image visibly contains buildings but receives no accepted elements, illustrating remaining element-recall limitations. No lighting label is forced. These observations are not proof of an accuracy gain from the new prompts; the earlier sample and prompts are not a controlled paired benchmark.']
    lines += ['','## Confusion matrices and mistakes','', 'Rows = review label; columns = model prediction. Uncertain predictions are abstentions, not automatic exclusions. A decisive prediction on a review-uncertain image is an overcommitment needing review.','```json',json.dumps({s:v['evaluation'] for s,v in report['strata'].items()},indent=2),'```',
              '', '## Fixed policy and limitations','```json',json.dumps(POLICY,indent=2),'```',
              '', 'Scores are cosine similarities, not calibrated probabilities. An irrelevant decision marks the image excluded from destination analysis without deleting the photo or earlier analyses. Uncertain decisions remain in a needs-review queue; detailed destination classification is deferred. Relevant images alone receive the new contrastive environment/element/condition analysis. Capture timestamps remain untouched.',
              '', 'The model still has prompt sensitivity, portrait/advertisement overlap, uncertain destination context, small-element limitations, and visually ambiguous lighting. Geographic balance alone does not establish semantic representativeness, tourism demand, image authenticity, or precise location. Larger independently human-labelled development and held-out sets are required before threshold calibration or accuracy claims.']
    parts.append('</html>');(directory/'previews.html').write_text(''.join(parts))
    Path('RELEVANCE_VALIDATION.md').write_text('\n'.join(lines)+'\n')
    return {key:value for key,value in report.items() if key!='rows'}
