"""Deterministic photo facts, named-place mentions, themes and geography from stored records."""
from html import unescape
import json
import re
from .licences import interpret
from .taxonomy import (AMBIGUOUS_AGRICULTURE_TERMS, ARABIC_STOP_WORDS, ARABIC_TYPES, CITIES, CITY_FEATURE_TYPES, GAZETTEER,
                       GENERIC_NAME_WORDS, INLAND_REGIONS, MAX_TRUSTED_TAGS, OUTSIDE_SAUDI, PREFIX_TYPES, REGIONS, SUFFIX_TYPES,
                       THEMES, TRAILING_NAME_WORDS, normalize)

_NAME_WORD = r"[A-Z][\w’'‘ʼ\-]*"
_SUFFIX = re.compile(rf"((?:{_NAME_WORD}\s+){{1,4}}?)((?i:{'|'.join(SUFFIX_TYPES)}))\b")
_PREFIX = re.compile(rf"\b({'|'.join(p.capitalize() for p in PREFIX_TYPES)})\s+((?:{_NAME_WORD}\s*){{1,3}})")
_ARABIC_WORD = r'[ء-يـً-ٟ]+'
_ARABIC = re.compile(rf"(?<![ء-ي])({'|'.join(ARABIC_TYPES)})\s+({_ARABIC_WORD}(?:\s+{_ARABIC_WORD}){{0,3}})")
_CAMERA_DETAILS = re.compile(r'(?i)camera model|shutter speed|exif|iso speed|focal length|lens ')
_TAG_NOISE = re.compile(r'(?i)^(sony|canon|nikon|samsung|iphone|instagram|uploaded:by|ilce|dsc|tokina|leica|nikkor|square format)')


def _clean_html(value):
    text = unescape(re.sub(r'<[^>]+>', ' ', str(value or '')))
    return re.sub(r'\s+', ' ', re.sub(r'https?://\S+|www\.\S+', ' ', text)).strip()


def _content(value):
    return value.get('_content') if isinstance(value, dict) else value


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def photo_facts(row, status=None):
    """Every field is copied from the record; absent values stay None rather than being estimated."""
    raw = json.loads(row['raw']) if isinstance(row['raw'], str) else (row['raw'] or {})
    envelope = raw.get('info')
    info = (envelope.get('photo') or {}) if isinstance(envelope, dict) else raw
    location = info.get('location') if isinstance(info.get('location'), dict) else {}
    owner = info.get('owner') if isinstance(info.get('owner'), dict) else {}
    favorites = raw.get('favorites') if isinstance(raw.get('favorites'), dict) else {}
    favorites = favorites.get('photo') if isinstance(favorites.get('photo'), dict) else {}
    comments = info.get('comments') if isinstance(info.get('comments'), dict) else {}
    description = _clean_html(_content(info.get('description')))
    if _CAMERA_DETAILS.search(description):
        description = _CAMERA_DETAILS.split(description)[0].strip()
    tags = json.loads(row['tags']) if isinstance(row['tags'], str) and row['tags'] else (row['tags'] or [])
    tags = [str(t) for t in tags if not _TAG_NOISE.match(str(t))]
    license_id = (status or {}).get('current_license_id') or row['license_id']
    original = None
    if info.get('originalsecret') and info.get('server'):
        original = f"https://live.staticflickr.com/{info['server']}/{row['photo_id']}_{info['originalsecret']}_o.{info.get('originalformat') or 'jpg'}"
    return {'source': row['source'], 'photo_id': row['photo_id'], 'metadata_available': bool(info),
            'title': (row['title'] or '').strip(), 'description': description, 'tags': tags,
            'latitude': row['latitude'], 'longitude': row['longitude'], 'accuracy': _int(location.get('accuracy', info.get('accuracy'))),
            'neighbourhood': _content(location.get('neighbourhood')), 'locality': _content(location.get('locality')),
            'county': _content(location.get('county')), 'flickr_region': _content(location.get('region')),
            'country': _content(location.get('country')), 'macro_sampling_region': raw.get('historical_region') or row.get('region'),
            'views': row['views'], 'favorites': _int(favorites.get('total')), 'comments': _int(comments.get('_content')),
            'owner_id': row['owner_id'], 'photographer': owner.get('realname') or owner.get('username') or None,
            'photo_url': row['photo_url'], 'original_url': original, 'license': interpret(license_id),
            'license_recorded_id': row['license_id'], 'captured_at': row['captured_at'], 'uploaded_at': row['uploaded_at']}


def _word_pattern(term):
    return r'(?<![\w])(?:ال|و|ب|ف)?' + re.escape(normalize(term)).replace(r'\ ', r'\s+') + r'(?![\w])'


_ALIASES = sorted(((normalize(a), g) for g in GAZETTEER for a in g['aliases'] + [g['name']]), key=lambda v: -len(v[0]))
_ALIAS_PATTERNS = [(re.compile(_word_pattern(a)), g) for a, g in _ALIASES]


def _gazetteer_hits(text, field):
    found, target = [], normalize(text)
    for pattern, group in _ALIAS_PATTERNS:
        if pattern.search(target) and group['name'] not in {f['name'] for f in found}:
            found.append({'name': group['name'], 'name_ar': group['ar'], 'type': group['type'], 'region': group['region'],
                          'field': field, 'method': 'alias_match', 'specificity': 'specific_place'})
    return found


def _arabic_words(lead):
    kept = []
    for word in lead.split():
        if normalize(word) in ARABIC_STOP_WORDS:
            break
        kept.append(word)
    return kept


def _english_words(lead):
    words = lead.split()
    while words and normalize(words[0]) in GENERIC_NAME_WORDS:
        words.pop(0)
    while words and normalize(words[-1]) in TRAILING_NAME_WORDS:
        words.pop()
    return words


def _classify(name_key, lead_key, kind):
    if lead_key in CITIES or name_key in CITIES:
        return 'city_feature' if kind in CITY_FEATURE_TYPES else 'specific_place'
    return 'specific_place'


def _pattern_mentions(text, field):
    """Name + place type only. Generic phrases such as 'Old fort' never become destinations."""
    results = []
    for match in _PREFIX.finditer(text):
        words = _english_words(match.group(2))
        if words:
            kind = PREFIX_TYPES[match.group(1).lower()]
            name = f"{match.group(1)} {' '.join(words)}"
            results.append({'name': name, 'name_ar': None, 'type': kind, 'region': None, 'field': field,
                            'method': 'prefix_pattern', 'specificity': _classify(normalize(name), normalize(' '.join(words)), kind)})
    for match in _SUFFIX.finditer(text):
        words = _english_words(match.group(1))
        # "Wadi Laban Park" is already "Wadi Laban" from the prefix rule.
        if words and normalize(words[0]) not in PREFIX_TYPES:
            kind = SUFFIX_TYPES[match.group(2).lower()]
            name = f"{' '.join(words)} {match.group(2).capitalize()}"
            results.append({'name': name, 'name_ar': None, 'type': kind, 'region': None, 'field': field,
                            'method': 'suffix_pattern', 'specificity': _classify(normalize(name), normalize(' '.join(words)), kind)})
    for match in _ARABIC.finditer(text):
        words = _arabic_words(match.group(2))
        if words:
            kind = ARABIC_TYPES[match.group(1)]
            name = f"{match.group(1)} {' '.join(words)}"
            results.append({'name': name, 'name_ar': name, 'type': kind, 'region': None, 'field': field,
                            'method': 'arabic_pattern', 'specificity': _classify(normalize(name), normalize(' '.join(words)), kind)})
    return results


def _strongest(results):
    """A pattern match that repeats a known alias or an existing name adds nothing."""
    aliases = {normalize(a): g['name'] for g in GAZETTEER for a in g['aliases'] + [g['name']]}
    known = {r['name'] for r in results if r['method'] == 'alias_match'}
    seen, final = set(), []
    for item in sorted(results, key=lambda r: (r['method'] != 'alias_match', {'title': 0, 'tags': 1, 'description': 2}[r['field']], len(r['name']))):
        key = normalize(item['name'])
        if item['method'] != 'alias_match' and (aliases.get(key) in known or any(key in normalize(n) or normalize(n) in key for n in known)):
            continue
        if any(key == other or key.startswith(other + ' ') for other in seen):
            continue
        seen.add(key)
        final.append(item)
    return final


def find_places(facts):
    """Title patterns and aliases; tags and descriptions only ever contribute known aliases or
    prefixed English names, because free text there is far noisier than a title."""
    title = facts['title']
    results = _gazetteer_hits(title, 'title') + _pattern_mentions(title, 'title')
    results += _gazetteer_hits(' , '.join(facts['tags']), 'tags')
    description = facts['description'][:400]
    results += _gazetteer_hits(description, 'description')
    results += [m for m in _pattern_mentions(description, 'description') if m['method'] == 'prefix_pattern']
    return sorted(_strongest(results), key=lambda r: ({'title': 0, 'tags': 1, 'description': 2}[r['field']], r['name']))


_THEME_PATTERNS = {key: [(term, re.compile(_word_pattern(term))) for term in value['terms']] for key, value in THEMES.items()}


def find_themes(facts, visual_environment=None, region=None):
    """Theme evidence keeps its source. Stored OpenCLIP labels are used only when already accepted."""
    fields = {'title': normalize(facts['title']), 'tags': normalize(' , '.join(facts['tags'])),
              'description': normalize(facts['description'][:600])}
    tag_spam = len(facts['tags']) > MAX_TRUSTED_TAGS
    matched = {}
    for key, value in THEMES.items():
        evidence = []
        for field, text in fields.items():
            terms = sorted({term for term, pattern in _THEME_PATTERNS[key] if pattern.search(text)})
            if terms:
                evidence.append({'source': field, 'terms': terms})
        if visual_environment and visual_environment in value['visual']:
            evidence.append({'source': 'openclip_stored', 'terms': [visual_environment]})
        if evidence:
            matched[key] = evidence
    themes = []
    for key, evidence in matched.items():
        sources = {e['source'] for e in evidence}
        strong = 'title' in sources or ('tags' in sources and not tag_spam)
        if key == 'coastal_marine' and 'title' not in sources and region in INLAND_REGIONS:
            strong = False
        if key == 'agricultural_tourism' and 'title' not in sources:
            terms = {t for e in evidence for t in e['terms']}
            if terms <= AMBIGUOUS_AGRICULTURE_TERMS and {'coastal_marine', 'urban_leisure_events'} & set(matched):
                strong = False
        strength = 'metadata' if strong else 'visual' if 'openclip_stored' in sources else 'weak_mention'
        themes.append({'theme': key, 'strength': strength, 'evidence': evidence})
    return themes


_REGION_PATTERNS = [(key, re.compile(_word_pattern(alias))) for key, value in REGIONS.items() for alias in value['aliases']]
_REGION_EXACT = {normalize(alias): key for key, value in REGIONS.items() for alias in value['aliases']}


def text_regions(facts):
    text = normalize(' , '.join([facts['title'], *facts['tags']]))
    return sorted({key for key, pattern in _REGION_PATTERNS if pattern.search(text)})


def resolve_geography(facts, places=()):
    """Records what is known and how. A geotag locates the camera; it does not identify a subject."""
    accuracy, flickr = facts['accuracy'], normalize(facts['flickr_region'])
    has_point = facts['latitude'] is not None and facts['longitude'] is not None
    outside = flickr in OUTSIDE_SAUDI or normalize(facts['locality']) in OUTSIDE_SAUDI
    region, basis = None, None
    if flickr in _REGION_EXACT:
        region, basis = _REGION_EXACT[flickr], 'flickr_location'
    if not region:
        for field in ('county', 'locality', 'neighbourhood'):
            key = _REGION_EXACT.get(normalize(facts[field]))
            if key:
                region, basis = key, 'flickr_' + field
                break
    mentioned = text_regions(facts)
    place_regions = sorted({p['region'] for p in places if p.get('region')})
    if not region and len(place_regions) == 1:
        region, basis = place_regions[0], 'named_place_alias'
    if not region and len(mentioned) == 1:
        region, basis = mentioned[0], 'title_or_tag_mention'
    if not has_point:
        precision = 'region_only' if region else 'macro_sampling_only' if facts['macro_sampling_region'] else 'unknown'
    elif accuracy is not None and accuracy >= 15:
        precision = 'precise_geotag'
    elif accuracy is not None and accuracy >= 11:
        precision = 'city_level_geotag'
    else:
        precision = 'coarse_geotag'
    conflict = bool(region and mentioned and region not in mentioned and basis == 'flickr_location')
    return {'precision': precision, 'latitude': facts['latitude'], 'longitude': facts['longitude'], 'flickr_accuracy': accuracy,
            'neighbourhood': facts['neighbourhood'], 'locality': facts['locality'], 'county': facts['county'],
            'flickr_region': facts['flickr_region'], 'region': None if outside else region, 'region_basis': None if outside else basis,
            'mentioned_regions': mentioned, 'macro_sampling_region': facts['macro_sampling_region'],
            'text_location_conflict': conflict, 'outside_saudi_metadata': outside,
            'note': 'Macro sampling region is the archive grouping, not an administrative boundary.'}
