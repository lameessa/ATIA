"""Turn photo evidence into signals for opportunity cards.

A signal says "this much user-generated evidence points here". It is not a verified
destination, a demand estimate, or a claim that anything is overlooked.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from statistics import median
import uuid
from atia.moderation.display import can_display
from atia.moderation.policy import exists
from .extract import find_places, find_themes, photo_facts, resolve_geography
from .store import IntelligenceStore
from .taxonomy import GAZETTEER, REGIONS, THEMES, normalize

VERSION = 'flickr-intelligence-v1'
NOT_ASSESSED = {'promotional_coverage': 'not_researched', 'underrepresentation': 'not_assessed', 'demand': 'not_assessed'}
SUBSET_OWNER_CAP = 3
SUBSET_PLACE_CAP = 2
SUBSET_MIN_EDGE = 640


def _visual_results(db):
    """Stored OpenCLIP output only. Nothing here runs a model."""
    results = {}
    if not exists(db, 'tourism_relevance'):
        return results
    for row in db.execute('SELECT * FROM tourism_relevance ORDER BY analyzed_at'):
        detail = json.loads(row['detail_result']) if row['detail_result'] else {}
        environment = detail.get('environment') or {}
        accepted = environment.get('label') if row['decision'] == 'relevant' and not environment.get('uncertain') else None
        spec = json.loads(row['model_spec']) if row['model_spec'] else {}
        results[(row['source'], row['photo_id'])] = {'decision': row['decision'], 'environment': accepted, 'model': spec.get('model_name'), 'analyzed_at': row['analyzed_at']}
    return results


def _review_labels(db):
    if not exists(db, 'visual_review_labels'):
        return {}
    return {(r['source'], r['photo_id']): r['label'] for r in db.execute('SELECT source, photo_id, label FROM visual_review_labels ORDER BY reviewed_at')}


def _lookup(db, table):
    if not exists(db, table):
        return {}
    return {(r['source'], r['photo_id']): dict(r) for r in db.execute(f'SELECT * FROM {table}')}


def _verified_entities(db):
    if not exists(db, 'verified_location_entities'):
        return {}
    return {normalize(r['verified_name']): dict(r) for r in db.execute(
        "SELECT * FROM verified_location_entities WHERE verification_status='authoritative_source_name_confirmed'")}


def _quality(photo, views_median):
    """Transparent points for how much an image can support; used only to order the review subset."""
    reasons = []
    def add(points, reason):
        reasons.append({'points': points, 'reason': reason})
    places = [p for p in photo['places'] if p['specificity'] == 'specific_place']
    if any(p['field'] == 'title' for p in places):
        add(3, 'named place in title')
    elif places:
        add(1, 'named place in tags or description')
    if any(t['strength'] == 'metadata' for t in photo['themes']):
        add(2, 'tourism theme in title or tags')
    if photo['geography']['precision'] == 'precise_geotag':
        add(2, 'precise geotag')
    elif photo['geography']['region']:
        add(1, 'known region')
    if photo['campaign_image_eligible']:
        add(2, 'licence allows campaign use')
    if photo['openclip'] and photo['openclip']['decision'] == 'relevant':
        add(1, 'stored OpenCLIP relevance')
    if photo['review_label'] == 'relevant':
        add(1, 'visual review marked relevant')
    if photo['image'] and max(photo['image']['width'], photo['image']['height']) >= 1000:
        add(1, 'image at least 1000px')
    if photo['engagement']['views'] is not None and views_median is not None and photo['engagement']['views'] >= views_median:
        add(1, 'views at or above archive median')
    if photo['engagement']['favorites']:
        add(1, 'has favorites')
    return {'score': sum(r['points'] for r in reasons), 'reasons': reasons}


def _photo_record(db, row, status, cache, visual, label):
    facts = photo_facts(row, status)
    places = find_places(facts)
    geography = resolve_geography(facts, places)
    openclip = visual.get((row['source'], row['photo_id']))
    themes = find_themes(facts, (openclip or {}).get('environment'), geography['region'])
    image = {k: cache[k] for k in ('width', 'height', 'fetched_at')} if cache else None
    checked = status and status['api_status'] == 'ok'
    displayable = can_display(db, row['source'], row['photo_id']) and not geography['outside_saudi_metadata']
    licence = facts['license']
    return {'source': row['source'], 'photo_id': row['photo_id'], 'title': facts['title'], 'tags': facts['tags'], 'description': facts['description'][:400],
            'photographer': facts['photographer'], 'owner_id': facts['owner_id'], 'photo_url': facts['photo_url'],
            'captured_at': facts['captured_at'], 'uploaded_at': facts['uploaded_at'], 'metadata_available': facts['metadata_available'],
            'flickr_status': status['api_status'] if status else 'not_checked', 'license': licence, 'license_recorded_id': facts['license_recorded_id'],
            'license_checked_at': status['checked_at'] if checked else None,
            'displayable': displayable, 'campaign_image_eligible': displayable and licence['campaign_eligible'],
            'engagement': {'views': facts['views'], 'favorites': facts['favorites'], 'comments': facts['comments']},
            'geography': geography, 'places': places, 'themes': themes, 'openclip': openclip, 'review_label': label, 'image': image,
            'preview_url': f"/api/images/{row['source']}/{row['photo_id']}" if displayable else None, 'subset_rank': None}


def _merge_places(photos):
    """Union names: same alias key, or an English and Arabic form of one type in one title."""
    parent = {}
    def find(key):
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key
    for photo in photos:
        title = [p for p in photo['places'] if p['field'] == 'title' and p['specificity'] == 'specific_place' and p['method'] != 'alias_match']
        for place in photo['places']:
            find(normalize(place['name']))
        for first in title:
            for second in title:
                if first['type'] == second['type'] and bool(first['name_ar']) != bool(second['name_ar']):
                    parent[find(normalize(first['name']))] = find(normalize(second['name']))
    groups = defaultdict(list)
    for photo in photos:
        for place in photo['places']:
            if place['specificity'] == 'specific_place':
                groups[find(normalize(place['name']))].append((photo, place))
    return groups


def _signal_id(kind, key):
    return 'signal-' + hashlib.sha256(f'{kind}:{key}'.encode()).hexdigest()[:16]


def _evidence(members):
    photographers = {m['owner_id'] for m in members if m['owner_id']}
    def total(field):
        values = [m['engagement'][field] for m in members if m['engagement'][field] is not None]
        return {'total': sum(values), 'photos_reporting': len(values)}
    years = sorted(m['captured_at'][:4] for m in members if m['captured_at'])
    return {'photo_count': len(members), 'distinct_photographers': len(photographers), 'views': total('views'), 'favorites': total('favorites'), 'comments': total('comments'),
            'capture_years': {'first': years[0], 'last': years[-1]} if years else None}


def _strength(evidence):
    photographers = evidence['distinct_photographers']
    return 'strong' if photographers >= 5 else 'moderate' if photographers >= 2 else 'thin'


def _geography(members):
    points = [m['geography'] for m in members if m['geography']['latitude'] is not None]
    precise = [g for g in points if g['precision'] == 'precise_geotag']
    used = precise or points
    centre = {'latitude': round(sum(g['latitude'] for g in used) / len(used), 6), 'longitude': round(sum(g['longitude'] for g in used) / len(used), 6),
              'basis': 'precise_geotags' if precise else 'lower_accuracy_geotags', 'note': 'Average camera position, not a surveyed location.'} if used else None
    regions = Counter(m['geography']['region'] for m in members if m['geography']['region'])
    localities = Counter(n for m in members for n in (m['geography']['neighbourhood'], m['geography']['locality']) if n)
    return {'regions': [{'key': k, 'en': REGIONS[k]['en'], 'ar': REGIONS[k]['ar'], 'photos': n} for k, n in regions.most_common()],
            'localities': [n for n, _ in localities.most_common(6)], 'macro_sampling_regions': dict(Counter(m['geography']['macro_sampling_region'] for m in members if m['geography']['macro_sampling_region'])),
            'centre': centre, 'geotagged_photos': len(points), 'precise_geotags': len(precise)}


def _images(members):
    shown = [m for m in members if m['displayable']]
    eligible = [m for m in shown if m['campaign_image_eligible']]
    ordered = sorted(shown, key=lambda m: (not m['campaign_image_eligible'], -m['quality']['score'], m['photo_id']))
    return {'displayable': len(shown), 'campaign_eligible': len(eligible), 'campaign_eligible_photo_ids': [m['photo_id'] for m in eligible],
            'representative': [{'source': m['source'], 'photo_id': m['photo_id'], 'preview_url': m['preview_url'], 'title': m['title'], 'photographer': m['photographer'],
                                'license': m['license']['name'], 'campaign_eligible': m['campaign_image_eligible']} for m in ordered[:4]]}


def _visual(members):
    stored = [m['openclip'] for m in members if m['openclip']]
    return {'photos_with_stored_result': len(stored), 'accepted_environments': dict(Counter(v['environment'] for v in stored if v['environment'])),
            'note': 'Stored results from an earlier OpenCLIP run. Similarities are not probabilities.'}


def _gaps(evidence, images, geography, identity=None, sensitive=None):
    gaps = []
    if not images['campaign_eligible']:
        gaps.append('no_campaign_eligible_image')
    if not images['displayable']:
        gaps.append('no_displayable_image')
    if evidence['distinct_photographers'] < 2:
        gaps.append('single_photographer')
    if not geography['precise_geotags']:
        gaps.append('no_precise_geotag')
    if identity and identity['status'] != 'verified_entity_exists':
        gaps.append('identity_unverified')
    if sensitive:
        gaps.append('requires_cultural_review')
    return gaps + ['promotional_coverage_not_researched']


def _base(kind, key, title, members, identity=None, theme=None, region=None, sensitive=None):
    evidence, images, geography = _evidence(members), _images(members), _geography(members)
    return {'signal_id': _signal_id(kind, key), 'kind': kind, 'key': key, 'title': title, 'strength': _strength(evidence), 'theme': theme, 'region': region,
            'identity': identity, 'evidence': evidence, 'images': images, 'geography': geography, 'visual': _visual(members), 'assessment': dict(NOT_ASSESSED),
            'sensitive_note': sensitive, 'gaps': _gaps(evidence, images, geography, identity, sensitive), 'photo_ids': sorted(m['photo_id'] for m in members),
            'status': 'signal_not_researched'}


def _named_signals(photos, entities):
    canonical = {g['name']: g for g in GAZETTEER}
    signals = []
    for key, items in _merge_places(photos).items():
        members = list({p['photo_id']: p for p, _ in items}.values())
        names = Counter(place['name'] for _, place in items)
        known = next((canonical[n] for n in names if n in canonical), None)
        english = known['name'] if known else next((n for n, _ in names.most_common() if not any('؀' <= c <= 'ۿ' for c in n)), None)
        arabic = known['ar'] if known else next((n for n, _ in names.most_common() if any('؀' <= c <= 'ۿ' for c in n)), None)
        entity = entities.get(normalize(known['name'])) if known else None
        identity = {'status': 'verified_entity_exists' if entity else 'unverified_metadata_name', 'entity_id': entity['entity_id'] if entity else None,
                    'place_type': (known or {}).get('type') or Counter(place['type'] for _, place in items).most_common(1)[0][0],
                    'name_sources': dict(Counter(place['field'] for _, place in items)), 'alias_group': bool(known),
                    'note': 'Verified means an authoritative source confirms the place exists, not that these photos show it.' if entity else 'Name read from Flickr metadata; existence not yet confirmed.'}
        signals.append(_base('named_destination', key, {'en': english, 'ar': arabic}, members, identity=identity))
    return signals


def _theme_signals(photos):
    regional, national = defaultdict(list), defaultdict(list)
    for photo in photos:
        for theme in photo['themes']:
            if theme['strength'] == 'weak_mention':
                continue
            national[theme['theme']].append(photo)
            if photo['geography']['region']:
                regional[(photo['geography']['region'], theme['theme'])].append(photo)
    signals = []
    for (region, theme), members in regional.items():
        info, place = THEMES[theme], REGIONS[region]
        signal = _base('regional_experience', f'{region}:{theme}', {'en': f"{info['en']} in {place['en']}", 'ar': f"{info['ar']} في {place['ar']}"}, members, theme=theme, region=region, sensitive=info.get('sensitive'))
        signal['features_mentioned'] = sorted({p['name'] for m in members for p in m['places'] if p['specificity'] == 'city_feature'})
        signals.append(signal)
    for theme, members in national.items():
        info = THEMES[theme]
        signal = _base('tourism_theme', theme, {'en': info['en'], 'ar': info['ar']}, members, theme=theme, sensitive=info.get('sensitive'))
        signal['archive_share'] = round(len(members) / max(1, len(photos)), 4)
        signal['terms_seen'] = dict(Counter(t for m in members for th in m['themes'] if th['theme'] == theme for e in th['evidence'] for t in e['terms']).most_common(8))
        signals.append(signal)
    return signals


def select_subset(photos, size):
    """Review set: evidence-bearing images, spread across archive regions, photographers and places."""
    def carries_evidence(photo):
        return any(t['strength'] != 'weak_mention' for t in photo['themes']) or any(x['specificity'] == 'specific_place' for x in photo['places'])
    # Chosen on evidence and image size, so review can start here. Selection grants no display permission.
    pool = [p for p in photos if p['image'] and carries_evidence(p) and max(p['image']['width'], p['image']['height']) >= SUBSET_MIN_EDGE]
    by_region = defaultdict(list)
    for photo in sorted(pool, key=lambda p: (-p['quality']['score'], p['photo_id'])):
        by_region[photo['geography']['macro_sampling_region'] or 'unknown'].append(photo)
    chosen, owners, places = [], Counter(), Counter()
    def fits(photo):
        names = {normalize(x['name']) for x in photo['places'] if x['specificity'] == 'specific_place'}
        return owners[photo['owner_id']] < SUBSET_OWNER_CAP and all(places[n] < SUBSET_PLACE_CAP for n in names), names
    while len(chosen) < size and any(by_region.values()):
        for region in sorted(by_region):
            while by_region[region]:
                photo = by_region[region].pop(0)
                allowed_here, names = fits(photo)
                if allowed_here:
                    owners[photo['owner_id']] += 1
                    places.update(names)
                    chosen.append(photo)
                    break
            if len(chosen) >= size:
                break
    for rank, photo in enumerate(chosen, 1):
        photo['subset_rank'] = rank
    return chosen


def _order(signals):
    rank = {'strong': 0, 'moderate': 1, 'thin': 2}
    return sorted(signals, key=lambda s: (rank[s['strength']], -s['images']['campaign_eligible'], -s['images']['displayable'], -s['evidence']['distinct_photographers'], -s['evidence']['photo_count'], s['key']))


def build_signals(db, subset_size=50):
    store = IntelligenceStore(db)
    store.initialize()
    statuses, caches = _lookup(db, 'photo_flickr_status'), _lookup(db, 'photo_image_cache')
    visual, labels = _visual_results(db), _review_labels(db)
    rows = [dict(r) for r in db.execute("SELECT * FROM photos WHERE source='afaq_historical' ORDER BY photo_id")]
    photos = [_photo_record(db, r, statuses.get((r['source'], r['photo_id'])), caches.get((r['source'], r['photo_id'])), visual, labels.get((r['source'], r['photo_id']))) for r in rows]
    views = [p['engagement']['views'] for p in photos if p['engagement']['views'] is not None]
    views_median = median(views) if views else None
    for photo in photos:
        photo['quality'] = _quality(photo, views_median)
    subset = select_subset(photos, subset_size)
    themed = _theme_signals(photos)
    signals = _order(_named_signals(photos, _verified_entities(db))) + _order([s for s in themed if s['kind'] == 'regional_experience']) + _order([s for s in themed if s['kind'] == 'tourism_theme'])
    run_id = 'intel-' + uuid.uuid4().hex
    created = datetime.now(timezone.utc).isoformat()
    count = lambda fn: sum(1 for p in photos if fn(p))
    summary = {
        'archive_photos': len(photos), 'metadata_available': count(lambda p: p['metadata_available']), 'flickr_status': dict(Counter(p['flickr_status'] for p in photos)),
        'images_cached': count(lambda p: p['image']), 'displayable': count(lambda p: p['displayable']), 'campaign_image_eligible': count(lambda p: p['campaign_image_eligible']),
        'licences': dict(Counter(p['license']['name'] or 'unknown' for p in photos)), 'licence_changed_since_archive': count(lambda p: p['flickr_status'] == 'ok' and str(p['license_recorded_id']) != str(p['license']['license_id'])),
        'geography': dict(Counter(p['geography']['precision'] for p in photos)), 'with_region': count(lambda p: p['geography']['region']),
        'stored_openclip_photos': count(lambda p: p['openclip']), 'with_named_place': count(lambda p: any(x['specificity'] == 'specific_place' for x in p['places'])),
        'with_theme': count(lambda p: any(t['strength'] != 'weak_mention' for t in p['themes'])), 'subset_size': len(subset), 'subset_campaign_eligible': sum(p['campaign_image_eligible'] for p in subset),
        'signals': dict(Counter(s['kind'] for s in signals)), 'signal_strength': {k: dict(Counter(s['strength'] for s in signals if s['kind'] == k)) for k in ('named_destination', 'regional_experience', 'tourism_theme')},
        'version': VERSION, 'openclip_note': 'Only stored results are used; this build does not run OpenCLIP.'}
    store.save(run_id, VERSION, created, summary, photos, signals)
    return {'run_id': run_id, 'summary': summary, 'signals': signals, 'photos': photos, 'subset': subset}


def write_report(result, path='FLICKR_INTELLIGENCE.md'):
    s = result['summary']
    lines = ['# ATIA Flickr intelligence', '', 'Generated by `atia intelligence build`. Deterministic: no paid service and no model was run. A signal is evidence pointing at something, not a verified destination, a demand estimate or a claim of being overlooked.', '',
             '## Archive', '', f"- Photographs: {s['archive_photos']}; with Flickr metadata: {s['metadata_available']}", f"- Current Flickr status: {s['flickr_status']}",
             f"- Displayable with a cached image: {s['displayable']}", f"- Eligible for campaign image use: {s['campaign_image_eligible']}", f"- Licences: {s['licences']}", f"- Geography: {s['geography']}; region known for {s['with_region']}",
             f"- Stored OpenCLIP results: {s['stored_openclip_photos']}", f"- Review subset: {s['subset_size']} ({s['subset_campaign_eligible']} campaign-eligible)", '']
    for kind, heading in (('named_destination', 'Named destinations'), ('regional_experience', 'Regional experiences'), ('tourism_theme', 'Tourism themes')):
        lines += [f'## {heading}', '', '| Signal | Strength | Photos | Photographers | Displayable | Campaign-eligible | Region |', '|---|---|---:|---:|---:|---:|---|']
        for signal in [x for x in result['signals'] if x['kind'] == kind]:
            title = signal['title']['en'] or signal['title']['ar']
            region = ', '.join(r['en'] for r in signal['geography']['regions'][:3]) or 'not known'
            lines.append(f"| {title} | {signal['strength']} | {signal['evidence']['photo_count']} | {signal['evidence']['distinct_photographers']} | {signal['images']['displayable']} | {signal['images']['campaign_eligible']} | {region} |")
        lines.append('')
    Path(path).write_text('\n'.join(lines))
