"""New prompt/policy versions. Existing dimensional prompts and results are immutable."""
import math
from atia.vision.dimensions import fingerprint

RELEVANCE = {
 'destination': {
  'landscape': ['a photograph of a scenic natural landscape', 'a photograph of a natural attraction with a wide view of the scenery'],
  'heritage': ['a photograph of a heritage site with traditional architecture', 'a photograph of historical buildings or ancient ruins'],
  'architecture': ['a photograph of interesting architecture and buildings', 'a cityscape photograph showing architecture and streets'],
  'public_space': ['a photograph of a public square, park, or waterfront', 'a photograph of a public garden or pedestrian plaza'],
  'cultural_attraction': ['a photograph of a museum, monument, or cultural attraction', 'a photograph of a visitor attraction or traditional village'],
 },
 'irrelevant': {
  'advertisement': ['an advertisement with large promotional text and contact information', 'a promotional poster with a phone number over a portrait'],
  'portrait': ['a close-up portrait photograph of a person', 'a posed portrait with a person as the main subject'],
  'selfie': ['a selfie photograph taken by a person', 'a close-up selfie inside a room or a car'],
  'product': ['a product photograph of an item for sale', 'a close-up photograph of food or a household object'],
  'screenshot': ['a screenshot of a website or mobile application', 'a graphic poster with text rather than a photograph of a place'],
  'unrelated_scene': ['a photograph of aircraft flying against the sky', 'a photograph focused on vehicles with no destination context'],
 },
}
ENVIRONMENTS = {
 'urban': ['an urban cityscape with buildings and streets', 'a photograph of a city street'],
 'desert': ['a desert landscape with sand dunes', 'a photograph of arid desert scenery'],
 'mountain': ['a mountain landscape with rocky peaks', 'a photograph of mountainous scenery'],
 'coastal': ['a coastal landscape with a beach and sea', 'a photograph of a coastline'],
 'forest': ['a forest landscape with many trees', 'a photograph of woodland scenery'],
 'rural': ['a rural landscape with farmland and fields', 'a photograph of countryside scenery'],
 'historical': ['a photograph of ancient ruins or historical buildings', 'a photograph of old architecture at a heritage site'],
 'cultural': ['a photograph of traditional architecture in a village', 'a photograph of a monument or cultural attraction'],
}
# Contrastive alternatives are not claims of absence. Negation in CLIP is unreliable.
ELEMENTS = {
 'trees': (['a photo of a tree', 'a photo of many trees'], ['a photo of bare open ground', 'a photo of an indoor room']),
 'vegetation': (['a photo of plants and bushes', 'a photo of green vegetation'], ['a photo of bare rock and sand', 'a photo of paved concrete surfaces']),
 'cars': (['a photo of a car', 'a photo of parked cars'], ['a photo of an empty footpath', 'a photo of pedestrians on a walkway']),
 'roads': (['a photo of a road', 'a photo of a paved street'], ['a photo of an indoor room', 'a photo of a natural landscape']),
 'buildings': (['a photo of a building', 'a photo of several buildings'], ['a photo of open natural scenery', 'a close-up photo of a person']),
 'people': (['a photo of a person', 'a photo of a group of people'], ['a photo of an empty place', 'a photo of scenery and objects']),
 'water': (['a photo of a body of water', 'a photo of the sea, a lake, or a river'], ['a photo of dry land', 'a photo of paved streets']),
 'rock_formations': (['a photo of natural rock formations', 'a photo of large exposed rocks'], ['a photo of smooth sand dunes', 'a photo of buildings']),
 'sand': (['a photo of sand dunes', 'a photo of sandy ground'], ['a photo of paved ground', 'a photo of green grass']),
 'traditional_architecture': (['a photo of traditional architecture', 'a photo of an ornate old building'], ['a photo of a modern glass building', 'a photo of open natural scenery']),
}
CONDITIONS = {
 'daytime': ['a photograph in natural daylight', 'an outdoor scene during the day'],
 'nighttime': ['a photograph at night in darkness', 'an outdoor scene illuminated by streetlights at night'],
 'sunrise': ['a landscape in dawn light at sunrise', 'a landscape with the sun rising near the horizon'],
 'sunset': ['a landscape in evening light at sunset', 'a landscape with the sun setting near the horizon'],
 'cloudy': ['a photograph of an overcast cloudy sky', 'an outdoor scene under heavy clouds'],
 'foggy': ['a landscape covered by fog', 'an outdoor scene with mist obscuring the distance'],
}
CONTROLS = {
 'scene': ['a close-up portrait of a person', 'an advertisement with large text overlays', 'a selfie inside a room', 'aircraft against the sky'],
 'lighting': ['an indoor scene with artificial lighting', 'a close-up subject with the background hidden'],
 'weather': ['a clear blue sky', 'an indoor scene with no visible sky', 'a close-up portrait with no visible sky', 'aircraft smoke trails across a blue sky'],
}
DETAILS = {'environment': ENVIRONMENTS, 'elements': ELEMENTS, 'conditions': CONDITIONS, 'controls': CONTROLS}
SCREEN_VERSION = fingerprint(RELEVANCE)
DETAIL_VERSION = fingerprint(DETAILS)
# Frozen starting rules, specified before the new sample is reviewed/scored.
POLICY = {'minimum': 0.25, 'relevance_margin': 0.03,
          'detail_minimum': 0.25, 'detail_margin': 0.03,
          'contrast_margin': 0.03}
POLICY_VERSION = fingerprint(POLICY)


def text_catalog():
    catalog = {}
    for side, groups in RELEVANCE.items():
        for category, texts in groups.items():
            for i, text in enumerate(texts):catalog[f'screen/{side}/{category}/{i}'] = text
    for category, texts in ENVIRONMENTS.items():
        for i, text in enumerate(texts):catalog[f'environment/{category}/{i}'] = text
    for category, (positive, negative) in ELEMENTS.items():
        for side, texts in [('positive',positive),('alternative',negative)]:
            for i, text in enumerate(texts):catalog[f'elements/{category}/{side}/{i}'] = text
    for category, texts in CONDITIONS.items():
        for i, text in enumerate(texts):catalog[f'conditions/{category}/{i}'] = text
    for group, texts in CONTROLS.items():
        for i, text in enumerate(texts):catalog[f'controls/{group}/{i}'] = text
    return catalog


def mean_prefix(flat, prefix):
    values = [value for key,value in flat.items() if key.startswith(prefix+'/')]
    if not values:raise ValueError('Missing prompt scores: '+prefix)
    return sum(values)/len(values)


def validate_scores(flat):
    if not flat or not all(isinstance(v,(int,float)) and math.isfinite(v) and -1.0001<=v<=1.0001 for v in flat.values()):
        raise ValueError('Invalid cosine similarities')


def screen_decision(flat):
    validate_scores(flat)
    scores = {side:{label:mean_prefix(flat,f'screen/{side}/{label}') for label in groups} for side,groups in RELEVANCE.items()}
    positive = max(scores['destination'],key=scores['destination'].get)
    negative = max(scores['irrelevant'],key=scores['irrelevant'].get)
    p,n = scores['destination'][positive],scores['irrelevant'][negative]
    decision = 'uncertain'
    if p>=POLICY['minimum'] and p-n>=POLICY['relevance_margin']:decision='relevant'
    elif n>=POLICY['minimum'] and n-p>=POLICY['relevance_margin']:decision='irrelevant'
    return {'decision':decision,'destination_status':{'relevant':'eligible','irrelevant':'excluded','uncertain':'needs_review'}[decision],
            'scores':scores,'best_destination':positive,'best_irrelevant':negative,
            'destination_score':p,'irrelevant_score':n,'signed_margin':p-n,
            'prototype_scores':flat,'score_type':'cosine_similarity'}


def detail_decision(flat):
    validate_scores(flat)
    minimum,margin = POLICY['detail_minimum'],POLICY['detail_margin']
    environment = {label:mean_prefix(flat,f'environment/{label}') for label in ENVIRONMENTS}
    scene_control = max(v for k,v in flat.items() if k.startswith('controls/scene/'))
    ranking=sorted(environment,key=environment.get,reverse=True)
    best,second=ranking[:2]
    accepted=environment[best]>=minimum and environment[best]-environment[second]>=margin and environment[best]-scene_control>=POLICY['contrast_margin']
    env={'scores':environment,'strongest_match':best,'label':best if accepted else None,'uncertain':not accepted,'alternative_score':scene_control}
    elements={}
    for label in ELEMENTS:
        p=mean_prefix(flat,f'elements/{label}/positive');n=mean_prefix(flat,f'elements/{label}/alternative')
        elements[label]={'similarity':p,'alternative_similarity':n,'margin':p-n,
                         'status':'possible_match' if p>=minimum and p-n>=POLICY['contrast_margin'] else 'uncertain'}
    conditions={label:mean_prefix(flat,f'conditions/{label}') for label in CONDITIONS}
    light_control=max(v for k,v in flat.items() if k.startswith('controls/lighting/'))
    weather_control=max(v for k,v in flat.items() if k.startswith('controls/weather/'))
    light=sorted(('daytime','nighttime','sunrise','sunset'),key=conditions.get,reverse=True)
    strongest=light[0]
    supported=conditions[strongest]>=minimum and conditions[strongest]-conditions[light[1]]>=margin and conditions[strongest]-light_control>=POLICY['contrast_margin']
    weather=[key for key in ('cloudy','foggy') if conditions[key]>=minimum and conditions[key]-weather_control>=POLICY['contrast_margin']]
    return {'environment':env,'elements':{'per_label':elements,'possible_matches':[k for k,v in elements.items() if v['status']=='possible_match']},
            'conditions':{'scores':conditions,'lighting_label':strongest if supported else None,'lighting_uncertain':not supported,'weather_matches':weather,
                          'lighting_alternative_score':light_control,'weather_alternative_score':weather_control},'prototype_scores':flat}
