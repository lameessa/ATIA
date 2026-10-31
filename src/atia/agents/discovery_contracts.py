"""Complete, bilingual campaign and hidden-gem evidence contracts."""
from .contracts import obj,STRING,STRINGS,BILINGUAL,SYSTEM

VERSION='tourism-opportunity-campaign-v2'
QUOTE=obj({'source_ref':STRING,'quote':STRING})
GEM=obj({'classification':{'type':'string','enum':['potential_hidden_gem','supported_marketing_opportunity','established_attraction','unresolved']},
         'hypothesis':STRING,'supporting_evidence':{'type':'array','items':QUOTE},
         'contradicting_evidence':{'type':'array','items':QUOTE},'limitations':STRINGS})
CAMPAIGN=obj({
    'campaign_name':BILINGUAL,'central_concept':BILINGUAL,
    'destination':obj({'entity_id':STRING,'name':BILINGUAL,'verified_location':BILINGUAL,'verification_refs':STRINGS}),
    'opportunity_hypothesis':BILINGUAL,'objectives':{'type':'array','items':BILINGUAL,'minItems':1},
    'target_audience':BILINGUAL,'audience_rationale_hypothesis':BILINGUAL,
    'key_messages':{'type':'array','items':BILINGUAL,'minItems':1},'creative_direction':BILINGUAL,
    'social_posts':{'type':'array','minItems':2,'items':obj({'post_id':STRING,'channel':STRING,'caption':BILINGUAL})},
    'suggested_channels':STRINGS,
    'publishing_schedule':{'type':'array','minItems':2,'items':obj({'post_id':STRING,
        'days_after_human_approved_launch':{'type':'integer','minimum':0,'maximum':90},
        'local_time':STRING,'timezone':{'type':'string','enum':['Asia/Riyadh']},'channel':STRING,'activity':BILINGUAL})},
    'recommended_activities':{'type':'array','items':BILINGUAL,'minItems':1},
    'kpis_and_measurement':{'type':'array','minItems':1,'items':obj({'metric':BILINGUAL,'measurement_plan':BILINGUAL,
        'baseline':{'type':'string','enum':['UNMEASURED']},'proposed_target_hypothesis':BILINGUAL})},
    'risks_uncertainties_validation':{'type':'array','items':BILINGUAL,'minItems':1},
    'source_refs':STRINGS,
    'approved_photo_assets':{'type':'array','minItems':1,'items':obj({'source':{'type':'string','enum':['afaq_historical','flickr_live']},
        'photo_id':STRING,'image_sha256':STRING,'identity_mapping_ref':STRING,'usage_hypothesis':BILINGUAL})},
})
DECISION=obj({'selected_cluster_id':{'type':['string','null']},'selection_reason':STRING,
    'decision':{'type':'string','enum':['CREATE','UPDATE','INVESTIGATE','NO_ACTION']},'explanation':STRING,
    'claims':{'type':'array','items':obj({'claim':STRING,'evidence_refs':STRINGS})},
    'hidden_gem':GEM,'uncertainties':STRINGS,'next_actions':STRINGS,
    'previous_campaign_id':{'type':['string','null']},'campaign':{'anyOf':[CAMPAIGN,{'type':'null'}]}})

GOAL='Independently discover and investigate one Saudi tourism marketing opportunity, including potential hidden gems; create or update a complete evidence-backed bilingual campaign only if justified.'
PROMPT=SYSTEM+'''
DISCOVERY MODE overrides the legacy proposal contract: use campaign, not proposal.
You choose the candidate; the user supplies neither destination nor campaign prompt.
Retrieve eligible areas, compare evidence and choose which to inspect. Use verified
names when known; neutral geographic identifiers are not official destinations.
Do NOT rank hiddenness by photo counts, views, favorites, sparse sentiment or missing
search hits. Established/iconic attractions and existing promotion can contradict a
hidden-gem hypothesis. Use stored Tavily research first; one further search at most.
Return selected_cluster_id for an area actually inspected. A hypothesis is not fact.
For hidden-gem support/counterevidence use verbatim excerpts from actual returned
source evidence, not your own generated summaries. At least TWO distinct publishers
and a directly supported lesser-known/niche-discovery statement are required for a
CREATE/UPDATE. Missing coverage is never positive evidence of hiddenness.
Source-confirmed entity existence does not authenticate the Flickr-photo association.
Campaigns need verified identity/location AND photo-to-entity reviewed mappings.
Use only returned eligible approved assets with their exact hashes and mapping refs.
Uncertain environment classification is not proof of image unsafety; explicit uncertain
image/relevance reviews are excluded. Live images require explicit user approval.
If identity, photo mapping, hidden-gem evidence or suitable assets are missing, prefer
INVESTIGATE. NO_ACTION is valid for established places with no justified opportunity.
Never force CREATE for a demo. A failed campaign gate cannot be repaired with invented
evidence. CREATE/UPDATE require every bilingual field, two social posts and a concrete
relative schedule (days AFTER human-approved launch, local time, Asia/Riyadh). Objectives,
audiences, creative concepts, captions, target KPIs and activities are proposals or
hypotheses, not observed performance. Baselines are UNMEASURED; invent no statistics,
audience studies, dates of real events, opening hours or performance. Keep copy concise
to fit the configured output cap. Include source references and required validations.
Review memory: CREATE only if no existing campaign for the entity; UPDATE references a
real prior campaign and genuinely changed evidence. All campaigns stay PENDING_APPROVAL.
No publishing tools exist; never execute a publishing schedule or start a recurring job.
GENERAL OPPORTUNITY MODE: a supported_marketing_opportunity may concern an established
destination's source-described visitor experience, not an inferred promotional gap.
It still requires two independent publishers, exact supporting quotes, verified identity,
reviewed approved images and every campaign guard. Quote an affirmative visitor route,
guided tour, cultural experience, heritage trail or nature reserve basis. Do not claim
hidden-gem status, underpromotion, demand or comparative popularity in that campaign.
The lesser-known statement requirement above applies only to potential_hidden_gem.
Copy source content_excerpt verbatim when quoting, or leave supporting evidence empty
and INVESTIGATE. inspect_candidate already includes memory; do not reread unchanged
memory just to consume the last tool call. Use the remaining search only if needed.
'''
