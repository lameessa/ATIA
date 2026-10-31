"""Conservative campaign admission. Reference validity is not full entailment."""
import re
import hashlib
from atia.moderation.policy import clean_evidence
from atia.research.tool import authoritative
from .storage import digest
from .discovery_contracts import DECISION

LESSER_KNOWN=('lesser-known','lesser known','less-known','little-known','little known','off the beaten track','off the beaten path',
              'under-visited','less visited','الأقل شهرة','غير معروفة','أقل شهرة')
ESTABLISHED=('popular attraction','popular destination','world-famous','world famous','iconic attraction','most visited','major tourism destination')


def excerpt(source):
    return source.get('content_excerpt') or source.get('evidence') or ''


def quote_source(tools,item):
    ref=item['source_ref'];tools.validate_refs([ref]);source=tools.refs[ref]
    if not isinstance(source,dict) or not ref.startswith('https://') or not source.get('publisher'):
        raise ValueError('Hidden-gem evidence needs an actual publisher/source URL')
    quote=' '.join(item['quote'].split()).casefold();text=' '.join(excerpt(source).split()).casefold()
    if len(quote)<20 or quote not in text:raise ValueError('Evidence excerpt was not actually returned by a source')
    return source


def campaign_fingerprint(tools,decision):
    campaign=decision['campaign'];refs=campaign['source_refs']
    return digest({'entity_id':campaign['destination']['entity_id'],
        'source_content':sorted((r,digest(excerpt(tools.refs[r]))) for r in refs),
        'assets':sorted((a['source'],a['photo_id'],a['image_sha256'],a['identity_mapping_ref']) for a in campaign['approved_photo_assets']),
        'geography':tools.data['cluster']['centroid']})


def guarded_discovery_decision(decision,tools):
    from .runner import validate,validate_claims
    validate(decision,DECISION);validate_claims(decision,tools)
    selected=decision['selected_cluster_id']
    if selected is None:
        if tools.pool or decision['decision'] not in ('NO_ACTION','INVESTIGATE'):raise ValueError('An eligible candidate must be inspected before a destination decision')
    else:
        if selected not in tools.inspected:raise ValueError('Final destination was never inspected')
        tools.select(selected)
    gem=decision['hidden_gem']
    for q in gem['supporting_evidence']+gem['contradicting_evidence']:quote_source(tools,q)
    if gem['classification']=='established_attraction' and not any(
        any(term in q['quote'].casefold() for term in ESTABLISHED) for q in gem['contradicting_evidence']):
        raise ValueError('Established/popular status also needs affirmative quoted evidence, not engagement or coverage counts')
    if decision['decision'] not in ('CREATE','UPDATE'):
        if decision['campaign'] is not None:raise ValueError('Only CREATE/UPDATE may produce a campaign')
        return decision
    general=gem['classification']=='supported_marketing_opportunity'
    if gem['classification']!='potential_hidden_gem' and not general:raise ValueError('No supported opportunity hypothesis')
    support=[quote_source(tools,q) for q in gem['supporting_evidence']]
    if len({s['publisher'].casefold() for s in support})<2:raise ValueError('Hidden-gem hypothesis needs two distinct source publishers')
    if not general and not any(any(term in q['quote'].casefold() for term in LESSER_KNOWN) for q in gem['supporting_evidence']):
        raise ValueError('No affirmative lesser-known evidence; missing results and engagement do not qualify')
    if general and not any(any(term in q['quote'].casefold() for term in ('visitor route','guided tour','cultural experience','heritage trail','walking trail','nature reserve')) for q in gem['supporting_evidence']):
        raise ValueError('General marketing hypothesis lacks affirmative visitor-experience source evidence')
    counters={q['source_ref'] for q in gem['contradicting_evidence']}
    for ref,value in tools.refs.items():
        if isinstance(value,dict) and any(term in excerpt(value).casefold() for term in ESTABLISHED) and ref not in counters:
            raise ValueError('Known established-attraction counterevidence was omitted')
    campaign=decision['campaign']
    if general:
        import json
        if any(term in json.dumps(campaign,ensure_ascii=False).casefold() for term in ('hidden gem','overlooked','underpromoted','جوهرة مخفية','غير مروج')):
            raise ValueError('A general visitor-experience campaign cannot assert hidden-gem status or a promotional gap')
    target=tools.data.get('target_entity_id') or getattr(tools,'target_entity_id',None)
    if target and campaign and campaign['destination']['entity_id']!=target:raise ValueError('Campaign changed the selected verified destination')
    if not campaign or not decision['uncertainties']:raise ValueError('Complete campaign and explicit uncertainty required')
    tools.validate_refs(campaign['source_refs']);tools.validate_refs(campaign['destination']['verification_refs'])
    if any(not r.startswith('https://') for r in campaign['source_refs']):raise ValueError('Campaign sources must be actual returned source URLs')
    required={q['source_ref'] for q in gem['supporting_evidence']+gem['contradicting_evidence']}|set(campaign['destination']['verification_refs'])
    if not required.issubset(campaign['source_refs']):raise ValueError('Campaign source list omitted cited support or counterevidence')
    entities=(tools.data['assessment'] or {}).get('entities',[])
    entity=next((e for e in entities if e['entity_id']==campaign['destination']['entity_id']),None)
    if entity is None:raise ValueError('Campaign destination lacks authoritative entity verification')
    if entity.get('verification_status')!='authoritative_source_name_confirmed':raise ValueError('Unverified destination identity')
    if entity['verified_name'].casefold() not in campaign['destination']['name']['en'].casefold():raise ValueError('Campaign name does not match verified entity')
    official={s['url'] for s in entity.get('sources',[]) if authoritative(s['url'])}
    if not official.intersection(campaign['destination']['verification_refs']):raise ValueError('Verified location needs its authoritative identity source')
    # Check every bilingual field, not just a top-level name.
    def bilingual(value):
        if isinstance(value,dict):
            if set(value)=={'en','ar'}:
                if not value['en'].strip() or not re.search('[\u0621-\u064a]',value['ar']):raise ValueError('Arabic and English content required for every campaign field')
            for v in value.values():bilingual(v)
        elif isinstance(value,list):
            for v in value:bilingual(v)
    bilingual(campaign)
    if not campaign['suggested_channels']:raise ValueError('Campaign channels missing')
    posts={p['post_id']:p for p in campaign['social_posts']}
    if len(posts)!=len(campaign['social_posts']):raise ValueError('Duplicate social post IDs')
    scheduled=set()
    for entry in campaign['publishing_schedule']:
        if entry['post_id'] not in posts or entry['channel']!=posts[entry['post_id']]['channel']:raise ValueError('Publishing schedule must reference a matching draft caption/channel')
        if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d',entry['local_time']):raise ValueError('Schedule needs a real local HH:MM time')
        scheduled.add(entry['post_id'])
    if scheduled!=set(posts):raise ValueError('Each draft caption must have an actionable relative schedule')
    for asset in campaign['approved_photo_assets']:
        ref='asset:'+asset['source']+':'+asset['photo_id']+':'+asset['image_sha256']
        if ref not in tools.assets:raise ValueError('Campaign asset not actually inspected/approved')
        path=tools.asset_paths[ref]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=asset['image_sha256']:raise ValueError('Approved campaign image bytes changed or disappeared')
        from .discovery_tools import eligible
        row=tools.memory.db.execute('SELECT * FROM photos WHERE source=? AND photo_id=?',(asset['source'],asset['photo_id'])).fetchone()
        if row is None or not eligible(tools.memory.db,dict(row)):raise ValueError('Campaign image approval revoked or image uncertain')
        tools.validate_refs([asset['identity_mapping_ref']]);mapping=tools.refs[asset['identity_mapping_ref']]
        if not isinstance(mapping,dict) or any(mapping.get(k)!=v for k,v in {'entity_id':entity['entity_id'],'photo_id':asset['photo_id'],'source':asset['source']}.items()):
            raise ValueError('No explicit photo-to-entity identity mapping')
    if not clean_evidence(tools.memory.db,campaign):raise ValueError('Blocked photo material in campaign')
    previous=tools.memory.db.execute('SELECT * FROM agent_campaigns WHERE entity_id=? ORDER BY created_at DESC LIMIT 1',(entity['entity_id'],)).fetchone()
    material=campaign_fingerprint(tools,decision)
    if previous and previous['evidence_fingerprint']==material:
        decision.update(decision='NO_ACTION',campaign=None,explanation='A campaign already exists for the same entity, source content and approved image evidence; no duplicate was created.')
        return decision
    if decision['decision']=='CREATE':
        if previous or decision['previous_campaign_id']:raise ValueError('Existing campaign requires UPDATE with genuinely new evidence')
    else:
        prior=tools.memory.db.execute('SELECT * FROM agent_campaigns WHERE campaign_id=? AND entity_id=?',
            (decision['previous_campaign_id'],entity['entity_id'])).fetchone()
        if prior is None:raise ValueError('UPDATE requires an existing campaign for the same entity')
        if prior['evidence_fingerprint']==material:raise ValueError('UPDATE has no materially new evidence')
    return decision


def fallback(reason,cluster_id=None):
    return {'selected_cluster_id':cluster_id,'selection_reason':'Insufficient validated evidence within the bounded discovery cycle.',
        'decision':'INVESTIGATE','explanation':reason,'claims':[],
        'hidden_gem':{'classification':'unresolved','hypothesis':'Not established','supporting_evidence':[],
                      'contradicting_evidence':[],'limitations':[reason]},
        'uncertainties':[reason],'next_actions':['Validate identity, approved-photo mapping and affirmative hidden-gem evidence before drafting.'],
        'previous_campaign_id':None,'campaign':None}
