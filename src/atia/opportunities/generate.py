"""One bounded OpenAI request: investigate one opportunity's evidence and draft a campaign.

The model sees real records and never chooses images. Deterministic checks decide what is saved.
"""
from dataclasses import replace
import json
import re
import time
import uuid
from atia.agents.contracts import BILINGUAL, PRICES, STRING, STRINGS, Limits, obj
from atia.agents.discovery_storage import DiscoveryStore
from atia.agents.runner import make_client, validate
from atia.agents.storage import digest, encode
from atia.intelligence.taxonomy import normalize
from atia.models import utc_now
from atia.moderation.policy import exists
from .store import OpportunityStore, initialize

VERSION = 'opportunity-campaign-v1'
# A full bilingual draft needs more room than the agent's step-by-step tool calls.
OUTPUT_TOKENS = 3500
GENERATION_TIMEOUT_SECONDS = 60
BILINGUAL_LIST = {'type': 'array', 'items': BILINGUAL, 'minItems': 1}
EDITOR_ONLY = ('destination', 'evidence_strength', 'evidence_label', 'review_evidence')
CAMPAIGN = obj({
    'campaign_name': BILINGUAL, 'central_concept': BILINGUAL, 'objectives': BILINGUAL_LIST, 'target_audience': BILINGUAL, 'audience_rationale_hypothesis': BILINGUAL,
    'positioning': BILINGUAL, 'opportunity_hypothesis': BILINGUAL, 'key_messages': BILINGUAL_LIST, 'creative_direction': BILINGUAL,
    'social_posts': {'type': 'array', 'minItems': 2, 'items': obj({'post_id': STRING, 'channel': STRING, 'caption': BILINGUAL})}, 'suggested_channels': {**STRINGS, 'minItems': 1},
    'publishing_schedule': {'type': 'array', 'minItems': 2, 'items': obj({'post_id': STRING, 'days_after_human_approved_launch': {'type': 'integer', 'minimum': 0, 'maximum': 90}, 'local_time': STRING,
                            'timezone': {'type': 'string', 'enum': ['Asia/Riyadh']}, 'channel': STRING, 'activity': BILINGUAL})},
    'kpis_and_measurement': {'type': 'array', 'minItems': 1, 'items': obj({'metric': BILINGUAL, 'measurement_plan': BILINGUAL, 'baseline': {'type': 'string', 'enum': ['UNMEASURED']}, 'proposed_target_hypothesis': BILINGUAL})},
    'risks_uncertainties_validation': BILINGUAL_LIST})
DECISION = obj({'decision': {'type': 'string', 'enum': ['CREATE', 'INVESTIGATE', 'NO_ACTION']}, 'recommendation': STRING, 'marketing_angle': STRING,
                'claims': {'type': 'array', 'items': obj({'claim': STRING, 'evidence_refs': STRINGS})}, 'uncertainties': STRINGS, 'next_actions': STRINGS, 'campaign': {'anyOf': [CAMPAIGN, {'type': 'null'}]}})
PROMPT = '''You are ATIA, a Saudi tourism marketing analyst. Investigate one opportunity using ONLY the supplied JSON evidence, then recommend whether to draft a campaign.

Evidence rules:
- The evidence is real Flickr user-generated data, with any stored research. Cite it in claims using the exact evidence_ref values.
- evidence_strength describes how many photographers support this. Say so plainly: "thin" evidence is an exploratory idea, and CREATE is still allowed for it if the draft states that.
- A regional or thematic opportunity does not need a named site or an exact farm. Never invent one.
- Do not read low engagement as underpromotion, or high engagement as demand. Do not say a place is a hidden gem, overlooked, underpromoted or undiscovered.
- identity "unverified_metadata_name" means the name comes from Flickr metadata. Do not describe it as officially confirmed.
- Invent no statistics, prices, opening hours, events, dates, facilities, routes, or audience research. Describe only what the evidence shows; anything else is a labelled hypothesis.
- Views, favourites and comments describe individual photographs. Never use them as evidence of interest, demand or appeal.
- Never claim growing or increasing interest, demand, popularity or trends, and never call anywhere leading, top, premier, best or a must-visit.
- Do not imply that tours, farm visits, workshops, tastings, tickets, bookings or other activities exist unless a supplied record shows them. Never write "join us". Marketing copy may invite people to see or discover the landscape shown. Anything to confirm belongs in risks_uncertainties_validation.
- Claims state what the photographs and their metadata show. KPI targets stay unquantified until a baseline is measured.

Decide:
- CREATE when the evidence supports a credible marketing angle, even if thin or without licensed images. Campaign images are handled separately; never mention specific images.
- Every decision must fill the top-level fields, not only the campaign. CREATE requires at least 2 entries in claims, each stating what the evidence shows and citing exact evidence_ref values, and at least 1 entry in uncertainties.
- INVESTIGATE when the evidence does not show what the opportunity claims. NO_ACTION when there is no credible angle. Both use campaign null.

Campaign rules: every field in natural English and natural Arabic (not word-for-word). Keep each field short: one or two sentences, 2-3 objectives and key messages, exactly 2 posts, each with a matching publishing_schedule entry (same post_id and channel; local_time HH:MM). Baselines are UNMEASURED and targets are hypotheses. List what a person must verify before launch in risks_uncertainties_validation.'''
# Stated as fact these would mislead, because Flickr data cannot show them. They block approval.
FACTUAL_CLAIMS = ('hidden gem', 'overlooked', 'underpromoted', 'under-promoted', 'undiscovered', 'جوهرة مخفية', 'غير مروج', 'غير مكتشف',
                  'growing interest', 'increasing interest', 'rising interest', 'growing demand', 'increasing demand', 'rising demand', 'high demand', 'strong demand', 'demand for',
                  'most popular', 'trending', 'most visited', 'اهتمام متزايد', 'اهتمام متنام', 'طلب متزايد', 'اقبال', 'الطلب على', 'الاكثر زيارة', 'الاكثر شهرة', 'book now', 'احجزوا')
# A person can judge promotional language, so these only warn.
PROMOTIONAL = ('leading', 'top destination', 'premier', 'best', 'number one', 'world class', 'must visit', 'unrivalled', 'رائدة', 'الرائدة', 'الافضل', 'افضل وجهة', 'join us', 'انضموا')
# Marketing copy may be judged by a person. In a claim of what the evidence shows, the records must say it.
POPULARITY = ('popular', 'popularity', 'sought after', 'شعبية')
# A short list for this MVP, not a content moderation system.
UNSAFE = ('escort', 'porn', 'pornographic', 'nude', 'sexual', 'temporary marriage', 'misyar', 'زواج مؤقت', 'زواج مسيار', 'اباحي')
# Offers are allowed only when a supplied record mentions them.
ACTIVITY_TERMS = {'tour': ('tour', 'tours', 'جولة', 'جولات'), 'visit offer': ('farm visit', 'farm visits', 'زيارات المزارع', 'زيارة المزارع'), 'workshop': ('workshop', 'workshops', 'ورشة', 'ورش'),
                  'tasting': ('tasting', 'tastings', 'تذوق'), 'ticket': ('ticket', 'tickets', 'تذاكر'), 'harvest activity': ('harvest activity', 'harvest activities', 'انشطة الحصاد'), 'booking': ('booking', 'bookings', 'حجز')}
# "Scenic views" describes scenery, not a Flickr metric.
ENGAGEMENT_WORDS = re.compile(r'\b(engagement|(?<!scenic )views?|favou?rites|comments|likes)\b|تفاعل|مشاهدات')
INTEREST_WORDS = re.compile(r'\b(interest|demand|popular\w*|appeal|attract\w*|resonat\w*)\b|اهتمام|طلب|اقبال')
ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')


def build_dossier(db, opportunity, store=None):
    """Only stored records. Missing analysis stays absent rather than being estimated."""
    run = db.execute('SELECT run_id FROM intelligence_runs ORDER BY created_at DESC, rowid DESC LIMIT 1').fetchone()
    photos = []
    for photo_id in opportunity['photo_ids'][:12]:
        row = db.execute('SELECT record FROM photo_intelligence WHERE run_id=? AND photo_id=?', (run['run_id'], photo_id)).fetchone()
        if not row:
            continue
        p = json.loads(row['record'])
        photos.append({'evidence_ref': 'photo:' + photo_id, 'title': p['title'], 'description': p['description'][:300], 'tags': p['tags'][:12], 'photographer': p['photographer'], 'photo_url': p['photo_url'],
                       'captured_at': p['captured_at'], 'engagement': p['engagement'], 'region': p['geography']['region'], 'locality': p['geography']['locality'], 'geotag_precision': p['geography']['precision'],
                       'themes': [t['theme'] for t in p['themes'] if t['strength'] != 'weak_mention'], 'stored_openclip': p['openclip']})
    research = []
    entity_id = (opportunity.get('identity') or {}).get('entity_id')
    if entity_id and exists(db, 'authoritative_entity_verifications'):
        row = db.execute('SELECT sources FROM authoritative_entity_verifications WHERE entity_id=? ORDER BY verified_at DESC LIMIT 1', (entity_id,)).fetchone()
        for source in json.loads(row['sources'])[:3] if row else []:
            research.append({'evidence_ref': 'research:' + source['url'], 'title': source.get('title'), 'publisher': source.get('publisher'), 'url': source['url'], 'excerpt': (source.get('content_excerpt') or source.get('evidence') or '')[:500]})
    return {'opportunity_id': opportunity['opportunity_id'], 'kind': opportunity['kind'], 'title': opportunity['title'], 'proposed_angle': opportunity['angle'], 'evidence_strength': opportunity['evidence_strength'],
            'identity': opportunity.get('identity'), 'totals': opportunity['evidence'], 'geography': {k: opportunity['geography'][k] for k in ('regions', 'localities', 'geotagged_photos', 'precise_geotags')},
            'photos': photos, 'stored_research': research, 'not_assessed': opportunity['assessment'], 'sensitive_note': opportunity.get('sensitive_note')}


def _bilingual(value):
    if isinstance(value, dict):
        if set(value) == {'en', 'ar'}:
            if not value['en'].strip() or not re.search('[ء-ي]', value['ar']):
                raise ValueError('Every campaign field needs English and Arabic')
        for item in value.values():
            _bilingual(item)
    elif isinstance(value, list):
        for item in value:
            _bilingual(item)


def _contains(text, term):
    return re.search(r'(?<!\w)(?:ال|و|ب)?' + re.escape(normalize(term)) + r'(?!\w)', text) is not None


def _check_language(decision, dossier, blocking, warnings):
    """Claims and persuasive copy only. Risks may name what still has to be confirmed."""
    campaign = decision['campaign']
    copy = {k: v for k, v in campaign.items() if k != 'risks_uncertainties_validation'}
    claims = normalize(json.dumps([c['claim'] for c in decision['claims']], ensure_ascii=False))
    text = normalize(json.dumps([copy, decision['recommendation'], decision['marketing_angle']], ensure_ascii=False)) + ' ' + claims
    records = normalize(json.dumps([dossier['photos'], dossier['stored_research']], ensure_ascii=False))
    blocking.extend(f'Unsafe content: {term}' for term in UNSAFE if _contains(text, term))
    blocking.extend(f'Draft asserts an unsupported claim: {term}' for term in FACTUAL_CLAIMS if _contains(text, term))
    warnings.extend(f'Promotional wording to review: {term}' for term in PROMOTIONAL if _contains(text, term))
    for term in POPULARITY:
        if _contains(claims, term) and not _contains(records, term):
            blocking.append(f'Claim says "{term}", which the supplied records do not show')
        elif _contains(text, term):
            warnings.append(f'Popularity wording to review: {term}')
    # The proposed angle is our own hypothesis, so it cannot be evidence that an activity exists.
    for label, terms in ACTIVITY_TERMS.items():
        if any(_contains(text, term) for term in terms) and not any(_contains(records, term) for term in terms):
            blocking.append(f'Draft implies an unverified activity: {label}')
    for claim in decision['claims']:
        wording = normalize(claim['claim'])
        if ENGAGEMENT_WORDS.search(wording) and INTEREST_WORDS.search(wording):
            blocking.append('Claim treats engagement as evidence of interest or demand')
            break


def _check_figures(campaign, dossier, blocking, warnings):
    """A figure in the copy must come from the evidence. A proposed KPI target is a plan, so it only warns."""
    copy = {k: v for k, v in campaign.items() if k not in ('publishing_schedule', 'kpis_and_measurement', 'social_posts')}
    copy['posts'] = [p['caption'] for p in campaign['social_posts']]
    copy['kpis'] = [{k: v for k, v in item.items() if k != 'proposed_target_hypothesis'} for item in campaign['kpis_and_measurement']]
    copy_text = json.dumps(copy, ensure_ascii=False).casefold().translate(ARABIC_DIGITS)
    # Whole numbers from what people wrote, so a digit inside a photo ID or URL proves nothing.
    written = json.dumps([[{k: p[k] for k in ('title', 'description', 'tags', 'engagement')} for p in dossier['photos']], [r['excerpt'] for r in dossier['stored_research']], dossier['totals']], ensure_ascii=False).translate(ARABIC_DIGITS)
    known = set(re.findall(r'\d[\d,.]*\d|\d', written))
    percentages = set(re.findall(r'(\d[\d,.]*)\s*%', written))
    for number in re.findall(r'(\d[\d,.]*)\s*%', copy_text):
        if number not in percentages:
            blocking.append(f'Draft contains a figure that is not in the evidence: {number}%')
    for number in re.findall(r'\d[\d,.]*\d', copy_text):
        if number not in known:
            blocking.append(f'Draft contains a figure that is not in the evidence: {number}')
    targets = json.dumps([item['proposed_target_hypothesis'] for item in campaign['kpis_and_measurement']], ensure_ascii=False).translate(ARABIC_DIGITS)
    warnings.extend(f'Proposed KPI target to review: {number}' for number in sorted(set(re.findall(r'\d[\d,.]*%?', targets))))


def assess_decision(decision, dossier):
    """Findings for a decision that already matches the schema: blocking errors stop approval, warnings inform it."""
    blocking, warnings = [], []
    refs = {p['evidence_ref'] for p in dossier['photos']} | {r['evidence_ref'] for r in dossier['stored_research']}
    if any(not claim['evidence_refs'] or not set(claim['evidence_refs']) <= refs for claim in decision['claims']):
        blocking.append('Claim cites evidence that was not supplied')
    campaign = decision['campaign']
    if decision['decision'] != 'CREATE':
        if campaign is not None:
            blocking.append('Only CREATE may include a campaign')
        return {'blocking': blocking, 'warnings': warnings}
    if not campaign:
        return {'blocking': blocking + ['CREATE needs a campaign'], 'warnings': warnings}
    if not decision['claims']:
        blocking.append('CREATE needs cited claims')
    if not decision['uncertainties']:
        blocking.append('CREATE needs stated uncertainties')
    try:
        _bilingual(campaign)
    except ValueError as exc:
        blocking.append(str(exc))
    posts = {p['post_id']: p for p in campaign['social_posts']}
    if len(posts) != len(campaign['social_posts']):
        blocking.append('Duplicate post IDs')
    scheduled = set()
    for entry in campaign['publishing_schedule']:
        if entry['post_id'] not in posts or entry['channel'] != posts[entry['post_id']]['channel']:
            blocking.append('Schedule must match a draft caption and channel')
        if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', entry['local_time']):
            blocking.append('Schedule needs a real HH:MM time')
        scheduled.add(entry['post_id'])
    if scheduled != set(posts):
        blocking.append('Every caption needs a schedule entry')
    _check_language(decision, dossier, blocking, warnings)
    _check_figures(campaign, dossier, blocking, warnings)
    return {'blocking': list(dict.fromkeys(blocking)), 'warnings': list(dict.fromkeys(warnings))}


def guard_decision(decision, dossier):
    """Raises ValueError for anything that must not be approved. Warnings do not raise."""
    validate(decision, DECISION)
    blocking = assess_decision(decision, dossier)['blocking']
    if blocking:
        raise ValueError(blocking[0])
    return decision


def repair_post_ids(decision):
    """Post IDs are internal keys with no meaning to a reader, so a clear pairing is renumbered in place."""
    campaign = decision.get('campaign') or {}
    posts, schedule = campaign.get('social_posts', []), campaign.get('publishing_schedule', [])
    if len({p['post_id'] for p in posts}) == len(posts) or len(posts) != len(schedule) or any(p['channel'] != s['channel'] for p, s in zip(posts, schedule)):
        return []
    for index, (post, entry) in enumerate(zip(posts, schedule), 1):
        post['post_id'] = entry['post_id'] = f'post-{index}'
    return ['The model reused a post ID, so ATIA renumbered the posts.']


def review_validation(content, evidence):
    """Checks the current revision, so correcting a draft clears its findings. Any failure to check blocks it."""
    try:
        review = content.get('review_evidence') or evidence
        decision = {'decision': 'CREATE', 'recommendation': review['recommendation'], 'marketing_angle': evidence['marketing_angle'], 'claims': review['claims'], 'uncertainties': review['uncertainties'],
                    'next_actions': [], 'campaign': {k: v for k, v in content.items() if k not in EDITOR_ONLY}}
        validate(decision, DECISION)
        findings = assess_decision(decision, evidence['dossier'])
    except (ValueError, TypeError, KeyError) as exc:
        findings = {'blocking': [f'This draft could not be checked: {exc}'[:200]], 'warnings': []}
    warnings = findings['warnings'] + evidence.get('repairs', [])
    state = 'NEEDS_CORRECTION' if findings['blocking'] else 'WARNINGS' if warnings else 'READY'
    return {'state': state, 'blocking': findings['blocking'], 'warnings': warnings}


def fallback(reason):
    return {'decision': 'INVESTIGATE', 'recommendation': reason, 'marketing_angle': 'Not established', 'claims': [], 'uncertainties': [reason], 'next_actions': ['Review the opportunity evidence before trying again.'], 'campaign': None}


def next_opportunity(db):
    """Autonomous choice: the highest-ranked opportunity without a live draft. Evidence strength orders it."""
    store = OpportunityStore(db)
    taken = {c['opportunity_id'] for c in store.campaigns() if _current_status(db, c) != 'REJECTED'}
    rank = {'strong': 0, 'moderate': 1, 'thin': 2}
    pool = [o for o in store.opportunities() if o['opportunity_id'] not in taken]
    return min(pool, key=lambda o: (rank[o['evidence_strength']], o['position']), default=None)


def _current_status(db, campaign):
    row = db.execute('SELECT decision FROM opportunity_review_events WHERE campaign_id=? ORDER BY rowid DESC LIMIT 1', (campaign['campaign_id'],)).fetchone()
    return row['decision'] if row else campaign['status']


def estimate(dossier, limits):
    instructions = len(PROMPT.encode()) + len(encode(DECISION).encode()) + len(encode(dossier).encode())
    prices = PRICES[limits.model]
    # Bytes over-count tokens, so this is an upper bound.
    return {'model': limits.model, 'input_bytes': instructions, 'max_output_tokens': OUTPUT_TOKENS, 'upper_bound_usd': round((instructions * prices[0] + OUTPUT_TOKENS * prices[1]) / 1_000_000, 5)}


def read_output(text, dossier):
    """A well-formed campaign is kept even with blocking findings. Raises when there is no campaign to keep."""
    decision = json.loads(text)
    validate(decision, DECISION)
    repairs = repair_post_ids(decision)
    if not decision['campaign'] or decision['decision'] != 'CREATE':
        guard_decision(decision, dossier)
    return decision, repairs


def save_draft(opportunities, opportunity, run_id, decision, fingerprint, dossier, repairs=()):
    campaign = {**decision['campaign'], 'destination': {'entity_id': (opportunity.get('identity') or {}).get('entity_id'), 'name': {'en': opportunity['title']['en'] or opportunity['title']['ar'], 'ar': opportunity['title']['ar'] or opportunity['title']['en']},
                'location_context': _location(opportunity)}, 'evidence_strength': opportunity['evidence_strength'], 'evidence_label': opportunity['evidence_label']}
    return opportunities.save_campaign(run_id, opportunity['opportunity_id'], campaign, fingerprint, {'dossier': dossier, 'claims': decision['claims'], 'uncertainties': decision['uncertainties'], 'recommendation': decision['recommendation'], 'marketing_angle': decision['marketing_angle'], 'repairs': list(repairs)})[0]


def recover_rejected(store):
    """Saves earlier model output that older, stricter checks refused. Reads stored runs; makes no model call."""
    db = store.connection
    initialize(db)
    opportunities = OpportunityStore(db)
    report = []
    for run in db.execute("SELECT * FROM agent_discovery_cycles WHERE status='needs_review' AND result_json IS NOT NULL ORDER BY created_at DESC").fetchall():
        result = json.loads(run['result_json'])
        opportunity = opportunities.opportunity(result.get('opportunity_id')) if result.get('rejected_output') else None
        if not opportunity or any(c['opportunity_id'] == opportunity['opportunity_id'] and _current_status(db, c) != 'REJECTED' for c in opportunities.campaigns()):
            continue
        dossier = build_dossier(db, opportunity)
        try:
            decision, repairs = read_output(result['rejected_output'], dossier)
        except (ValueError, TypeError, KeyError) as exc:
            report.append({'opportunity_id': opportunity['opportunity_id'], 'run_id': run['run_id'], 'saved': False, 'reason': str(exc)[:200]})
            continue
        if decision['decision'] != 'CREATE':
            continue
        campaign_id = save_draft(opportunities, opportunity, run['run_id'], decision, digest({'version': VERSION, 'dossier': dossier}), dossier, repairs)
        report.append({'opportunity_id': opportunity['opportunity_id'], 'run_id': run['run_id'], 'saved': True, 'campaign_id': campaign_id, **assess_decision(decision, dossier)})
    return report


def run_opportunity(store, opportunity_id=None, limits=None, client=None, progress=None):
    db = store.connection
    initialize(db)
    limits = limits or Limits.load()
    opportunities = OpportunityStore(db)
    opportunity = opportunities.opportunity(opportunity_id) if opportunity_id else next_opportunity(db)
    if not opportunity:
        raise ValueError('No opportunity is available')
    existing = next((c for c in opportunities.campaigns() if c['opportunity_id'] == opportunity['opportunity_id'] and _current_status(db, c) != 'REJECTED'), None)
    if existing:
        return {'run_id': existing['run_id'], 'campaign_id': existing['campaign_id'], 'opportunity_id': opportunity['opportunity_id'], 'decision': {'decision': 'NO_ACTION', 'recommendation': 'A draft already exists.'}, 'errors': [], 'estimated_api_cost_usd': 0}
    memory = DiscoveryStore(store)
    dossier = build_dossier(db, opportunity)
    fingerprint = digest({'version': VERSION, 'dossier': dossier})
    run_id = 'agent-' + uuid.uuid4().hex
    started = time.monotonic()
    goal = f"Investigate the marketing opportunity {opportunity['title']['en'] or opportunity['title']['ar']} and draft a campaign if justified."
    with db:
        db.execute('INSERT INTO agent_discovery_cycles(run_id,cluster_id,goal,created_at,cache_key,status,model,limits_json) VALUES(?,?,?,?,?,?,?,?)',
                   (run_id, None, goal, utc_now(), fingerprint, 'running', limits.model, encode(limits.to_dict())))
    errors, usd, usage, decision, rejected, repairs = [], 0.0, {'input_tokens': 0, 'output_tokens': 0}, None, None, []
    (progress or (lambda _: None))('Reviewing Flickr evidence for this opportunity.')
    payload = {'model': limits.model, 'instructions': PROMPT, 'input': [{'role': 'user', 'content': encode(dossier)}], 'max_output_tokens': OUTPUT_TOKENS, 'store': False,
               'text': {'format': {'type': 'json_schema', 'name': 'atia_opportunity', 'strict': True, 'schema': DECISION}}}
    prices = PRICES[limits.model]
    reserve = ((len(encode(payload).encode()) + 4096) * prices[0] + OUTPUT_TOKENS * prices[1]) / 1_000_000
    try:
        # A full bilingual draft can outlast the default; a timed-out request is still billed and is not retried.
        client = client or make_client(replace(limits, timeout_seconds=GENERATION_TIMEOUT_SECONDS))
        # Reserved only once a request can really be sent, so a missing key costs no budget.
        request = memory.reserve(run_id, 1, reserve, limits)
    except (ValueError, RuntimeError) as exc:
        errors.append(f'Not sent: {exc}')
    else:
        try:
            response = client.responses.create(**payload)
            usd = memory.finish_request(request, response, prices)
            usage = {'input_tokens': response.usage.input_tokens, 'output_tokens': response.usage.output_tokens}
            if response.status != 'completed':
                raise ValueError('The model response was incomplete; no paid retry was made.')
            rejected = response.output_text
            decision, repairs = read_output(rejected, dossier)
            rejected = None
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            errors.append(f'Draft rejected: {exc}')
        except Exception as exc:
            # Remote error bodies stay out of logs; the reservation is retained.
            errors.append(f'OpenAI request failed ({type(exc).__name__}, status={getattr(exc, "status_code", None)})')
    decision = decision or fallback(errors[0] if errors else 'No decision was returned.')
    campaign_id = None
    if decision['decision'] == 'CREATE':
        campaign_id = save_draft(opportunities, opportunity, run_id, decision, fingerprint, dossier, repairs)
    result = {'run_id': run_id, 'opportunity_id': opportunity['opportunity_id'], 'campaign_id': campaign_id, 'errors': errors, 'estimated_api_cost_usd': usd, 'usage': usage, 'llm_requests': 1, 'tool_calls': 0, 'elapsed_seconds': round(time.monotonic() - started, 3), 'agent_version': VERSION,
              'decision': {**decision, 'explanation': decision['recommendation'], 'hidden_gem': {'classification': 'not_assessed'}, 'campaign': None}, 'evidence_registry': {}}
    if campaign_id:
        result['validation'] = assess_decision(decision, dossier)
    # A paid response with no campaign to keep is stored for diagnosis.
    if rejected:
        result['rejected_output'] = rejected
    with db:
        db.execute('UPDATE agent_discovery_cycles SET status=?, completed_at=?, result_json=? WHERE run_id=?', ('needs_review' if errors else 'completed', utc_now(), encode(result), run_id))
    return result


def _location(opportunity):
    regions = opportunity['geography']['regions']
    return {'en': ', '.join(r['en'] for r in regions[:3]) or 'Saudi Arabia', 'ar': '، '.join(r['ar'] for r in regions[:3]) or 'المملكة العربية السعودية'}
