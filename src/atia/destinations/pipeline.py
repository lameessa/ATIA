from collections import Counter
import hashlib
import json
from pathlib import Path
import time
import uuid
from atia.destinations.geo import GeoPolicy,extract_geo,cluster,distance
from atia.destinations.storage import DestinationStore
from atia.destinations.evidence import EvidenceIndex


def fingerprint(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def verified_places(path):
    if not path:return {}
    values=json.loads(Path(path).read_text());result={}
    if not isinstance(values,list):raise ValueError('Verified places must be a JSON list')
    for value in values:
        if value.get('verified') is not True or value.get('level') not in {'destination_area','individual_attraction'} or not all(value.get(k) for k in ('source','photo_id','place_id','name','evidence_url','reviewer')):
            raise ValueError('Place annotations require verified=true, level, source/photo_id, place_id, name, reviewer and evidence_url')
        if not str(value['evidence_url']).startswith('https://'):raise ValueError('Verified place evidence must have an HTTPS source reference')
        key=(value['source'],str(value['photo_id']))
        if key in result:raise ValueError('Duplicate verified-place annotation')
        result[key]={k:value[k] for k in ('place_id','name','level','evidence_url','reviewer')}
    return result


def build_destinations(store,policy=None,places_path=None,progress=None):
    started=time.monotonic();policy=policy or GeoPolicy();emit=progress or (lambda message:None)
    records=[dict(r) for r in store.connection.execute('SELECT * FROM photos ORDER BY source,photo_id')]
    annotations=verified_places(places_path);storage=DestinationStore(store)
    policy_data={**policy.to_dict(),'place_annotations_hash':fingerprint(sorted((list(key),value) for key,value in annotations.items()))}
    key=fingerprint(policy_data)
    input_hash=fingerprint([{k:r[k] for k in sorted(r)} for r in records])
    points=[extract_geo(r,policy) for r in records]
    for point in points:
        if (point['source'],point['photo_id']) in annotations:point['verified_place']=annotations[(point['source'],point['photo_id'])]
    # Conflicting coordinate/locality versions for the same ID must not silently
    # turn two source observations into two destinations for one photograph.
    by_id={}
    for point in points:
        if point['unassigned_reason'] is None:by_id.setdefault(point['photo_id'],[]).append(point)
    from atia.destinations.geo import compatible
    for observations in by_id.values():
        if any(distance(a,b)>policy.distance_km or not compatible(a,b) for a in observations for b in observations):
            for point in observations:point['unassigned_reason']='conflicting_photo_location_versions'
    usable=[p for p in points if p['unassigned_reason'] is None]
    emit(f'Grouping {len(usable)} usable geotags from {len(points)} records; maximum diameter {policy.distance_km} km...')
    groups=cluster(usable,policy);identities=storage.identities(groups,key);index=EvidenceIndex(store.connection,records)
    destinations=[]
    for group,(identifier,parents) in zip(groups,identities):
        evidence=index.aggregate(group)
        diameter=max((distance(a,b) for a in group for b in group),default=0)
        localities={json.dumps(p['locality'],sort_keys=True,ensure_ascii=False):p['locality'] for p in group if p['locality']}
        regions={json.dumps(p['region'],sort_keys=True,ensure_ascii=False):p['region'] for p in group if p['region']}
        place_annotations={p['verified_place']['place_id']:p['verified_place'] for p in group if p.get('verified_place')}
        all_named=len(place_annotations)==1 and all(p.get('verified_place') for p in group)
        named=next(iter(place_annotations.values())) if all_named else None
        warnings=['geotags_not_independently_verified']
        if len(group)==1:warnings.append('single_photo_area_not_confirmed_destination')
        else:warnings.append('nearby_photos_may_show_different_attractions')
        if not named:warnings.append('attraction_identity_not_established')
        if evidence['distinct_photographers']<=1:warnings.append('single_photographer_evidence')
        if evidence['relevance_coverage'].get('irrelevant'):warnings.append('screened_irrelevant_content_present')
        if any(r['label']=='irrelevant' for r in evidence['review_annotations']):warnings.append('reviewed_irrelevant_content_present')
        if evidence['relevance_coverage'].get('not_evaluated'):warnings.append('unevaluated_images_are_not_assumed_irrelevant')
        if len(localities)>1:warnings.append('multiple_locality_spellings_or_boundaries_need_review')
        if diameter>policy.distance_km*.8:warnings.append('diameter_near_policy_limit')
        owners_by_coord={}
        for p in group:
            r=index.records[(p['source'],p['photo_id'])]
            if r['owner_id']:owners_by_coord.setdefault((p['latitude'],p['longitude']),set()).add(r['owner_id'])
        if any(len(owners)>1 for owners in owners_by_coord.values()):warnings.append('identical_coordinates_across_photographers_need_review')
        if len(parents)>1:warnings.append('multiple_previous_group_identities_overlap')
        destinations.append({'destination_id':identifier,'name':named['name'] if named else 'Unidentified destination area',
            'level':named['level'] if named else 'destination_area','name_status':'reviewer_verified_reference' if named else 'neutral_unverified',
            'name_reference':named,'parent_destination_ids':parents,
            'photo_ids':sorted({p['photo_id'] for p in group}),
            'centroid':{'latitude':sum(p['latitude'] for p in group)/len(group),'longitude':sum(p['longitude'] for p in group)/len(group),
                        'note':'Geographic centroid, not an identified attraction point'},
            'bbox':[min(p['longitude'] for p in group),min(p['latitude'] for p in group),max(p['longitude'] for p in group),max(p['latitude'] for p in group)],
            'maximum_pair_distance_km':round(diameter,6),'reported_localities':list(localities.values()),
            'reported_administrative_regions':list(regions.values()),'sampling_macro_regions':dict(Counter(p['macro_region'] or 'unknown' for p in group)),
            'verified_place_candidates':list(place_annotations.values()),'evidence':evidence,'warnings':warnings})
    report={'run_id':'dest-run-'+uuid.uuid4().hex,'policy':policy_data,'policy_key':key,'input_hash':input_hash,
            'total_photo_records':len(points),'global_relevance_coverage':dict(Counter(index.screen.get((r['source'],r['photo_id']),{}).get('decision','not_evaluated') for r in records)),'assigned_photo_records':len(usable),'assigned_unique_photo_ids':len({p['photo_id'] for p in usable}),
            'unassigned_photo_records':len(points)-len(usable),'unassigned_reasons':dict(Counter(p['unassigned_reason'] for p in points if p['unassigned_reason'])),
            'destination_groups':len(groups),'destination_levels':dict(Counter(d['level'] for d in destinations)),
            'naming':'Flickr localities/regions are contextual metadata, not verified attraction names. Neutral names are deliberate.',
            'eligibility':'Geographic grouping includes all suitable geotags regardless of screening coverage; not_evaluated is not irrelevant.',
            'destinations':sorted(destinations,key=lambda d:(-d['evidence']['photo_count'],d['destination_id']))}
    report['elapsed_seconds']=round(time.monotonic()-started,4)
    storage.save(report,policy_data,key,input_hash,points)
    report['elapsed_seconds']=round(time.monotonic()-started,4)
    # Include persistence timing in the stored inspection report too.
    with store.connection:store.connection.execute('UPDATE destination_runs SET report=? WHERE run_id=?',(json.dumps(report,ensure_ascii=False),report['run_id']))
    emit(f"Created {len(groups)} candidate areas; {len(usable)} assigned, {len(points)-len(usable)} unassigned in {report['elapsed_seconds']}s")
    return report


def write_report(report,path='DESTINATION_INTELLIGENCE.md'):
    lines=['# ATIA destination intelligence','',f"Run `{report['run_id']}`. Coordinate grouping and existing evidence only; no model inference, LLM clustering, geocoding claims, or promotional research.",
       '',f"**{report['destination_groups']} candidate areas; {report['assigned_photo_records']} assigned photo records; {report['unassigned_photo_records']} unassigned; {report['elapsed_seconds']} seconds.**",
       '', '## Geographic policy and naming','',f"Maximum group diameter: {report['policy']['distance_km']} km. Minimum Flickr accuracy level: {report['policy']['min_accuracy']}. Complete-link insertion prevents transitive chains from exceeding the diameter. Locality-ID conflicts are not merged. Accuracy is Flickr metadata, not a measured error radius or proof of correct user geotags.",
       '', report['naming'], 'All areas remain candidates; none becomes a confirmed tourism destination from image counts or engagement. Regions are context, not clusters. Individual attractions require explicit reviewed place annotations with source references. Titles are retained as photo metadata, never promoted to verified place names.',
       '', '## Assignment coverage','```json',json.dumps(report['unassigned_reasons'],indent=2),'```',
       '', '## All candidate groups','', '| Destination ID | Photos | Photographers | Centre (lat, lon) | Flickr-reported locality context | Relevance coverage |', '|---|---:|---:|---|---|---|']
    for group in report['destinations']:
        e=group['evidence'];loc=', '.join(p['name'] or p['woeid'] or '' for p in group['reported_localities']) or 'not available'
        lines.append(f"| {group['destination_id']} | {e['photo_count']} | {e['distinct_photographers']} | {group['centroid']['latitude']:.5f}, {group['centroid']['longitude']:.5f} | {loc.replace('|','/')} | {json.dumps(e['relevance_coverage'])} |")
    # Show the largest groups plus groups with AI or sentiment evidence, not just the biggest.
    examples=report['destinations'][:4]
    for group in report['destinations']:
        if len(examples)>=9:break
        if (group['evidence']['visual']['photos_with_dimensional_evidence'] or group['evidence']['sentiment']['classified_comments']) and group not in examples:examples.append(group)
    lines += ['','## Evidence examples']
    for group in examples:
        e=group['evidence'];lines += ['',f"### {group['destination_id']} — {group['name']}",
          '',f"Photo IDs: {', '.join(group['photo_ids'])}. Maximum pair distance: {group['maximum_pair_distance_km']:.3f} km. Sources: {e['sources']}; distinct known photographers: {e['distinct_photographers']}.",
          '',f"Visual possible environments: {e['visual']['possible_environment_counts']}; elements: {e['visual']['possible_element_counts']}; missing dimensional evidence: {e['visual']['missing_dimensional_photos']}; suppressed screened-irrelevant photos: {e['visual']['suppressed_screened_irrelevant_photos']}. Uncertain ranks remain separate: {e['visual']['uncertain_environment_top_ranks']}.",
          '',f"Views: {e['engagement']['views_sum_observed']} across {e['engagement']['views_available_photos']} photos. Favorites: {e['engagement']['favorites_sum_observed']} across {e['engagement']['favorites_available_photos']} photos. Missing values are unknown, not zero; totals combine unsynchronized snapshots.",
          '',f"Comment sentiment: {e['sentiment']['distribution']} from {e['sentiment']['classified_comments']} classified of {e['sentiment']['observed_unique_comments']} observed comments; {e['sentiment']['photos_without_fetch_evidence']} photos lack fetch evidence. These comments may describe photo technique, not destination opinion.",
          '',f"Upload bounds: {e['upload_dates']['minimum_as_recorded']} to {e['upload_dates']['maximum_as_recorded']}. Capture bounds: {e['capture_dates']['minimum_as_recorded']} to {e['capture_dates']['maximum_as_recorded']}; capture timezone unknown for {e['capture_dates']['timezone_unknown_photos']} photos.",
          '',f"Review flags: {', '.join(group['warnings'])}."]
    lines += ['', '## Potentially incorrect grouping and missing evidence','',
       'Nearby photos can depict different attractions, private places, or content with false geotags. A high Flickr accuracy level does not authenticate a location. Repeated exact coordinates across photographers and reviewed/automatically excluded advertisements are explicit risk flags, not evidence of popular destinations. Single-photographer clusters are weak corroboration. City-level locality names cannot identify a specific attraction.',
       '', 'Only 25 photos were screened in the relevance audit. All other photos keep not_evaluated status; no inference is made that they are irrelevant. The 197 historical photos retain curated-source provenance, independent of limited model coverage. Geographic assignment and tourism eligibility are distinct.',
       '', 'No available visual analysis, no sentiment analysis, no comment fetch, and a successful zero-comment response remain different states. Capture dates, upload dates, sources, model versions, missing metrics, and uncertain ranks are retained. Aggregates never treat positive sentiment, views, favorites, or photo counts as tourism demand.',
       '', '## Stable identities and provenance','',
       'Within a policy, destination IDs reuse maximum-overlap previous memberships when data grows; initial IDs are deterministic UUID-derived identifiers. Splits/merges retain one matching identity and record parent candidates. Previous runs and assignments are immutable snapshots. Changed distance/accuracy policies use a separate identity namespace. Greedy complete-link clustering is deterministic for a fixed input, not globally optimal. New observations can change boundaries and require review.',
       '', 'The SQLite destination tables are additive and do not overwrite photo, comment, sentiment, visual, relevance, or manual destination-mapping tables. Inspect full evidence JSON through the CLI; no autonomous decisions are implemented.']
    Path(path).write_text('\n'.join(lines)+'\n')
