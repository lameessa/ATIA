"""Flickr licence interpretation. Campaign use is opt-in per licence and uncertain means no.

IDs follow flickr.photos.licenses.getInfo. An ID describes what Flickr reported at one
moment; callers must say when it was checked, and this is not legal clearance.
"""

CAMPAIGN_ELIGIBLE = 'eligible_with_attribution'
EXCLUDED = 'excluded'
UNKNOWN = 'unknown'

_BY = 'https://creativecommons.org/licenses/'
LICENCES = {
    '0': ('All Rights Reserved', None, EXCLUDED, 'Requires permission from the photographer.'),
    '1': ('CC BY-NC-SA 2.0', _BY + 'by-nc-sa/2.0/', EXCLUDED, 'Non-commercial only; marketing is commercial use.'),
    '2': ('CC BY-NC 2.0', _BY + 'by-nc/2.0/', EXCLUDED, 'Non-commercial only; marketing is commercial use.'),
    '3': ('CC BY-NC-ND 2.0', _BY + 'by-nc-nd/2.0/', EXCLUDED, 'Non-commercial and no derivatives.'),
    '4': ('CC BY 2.0', _BY + 'by/2.0/', CAMPAIGN_ELIGIBLE, 'Attribution required.'),
    '5': ('CC BY-SA 2.0', _BY + 'by-sa/2.0/', CAMPAIGN_ELIGIBLE, 'Attribution required; adaptations must share alike.'),
    '6': ('CC BY-ND 2.0', _BY + 'by-nd/2.0/', EXCLUDED, 'No derivatives; campaign crops and overlays are adaptations.'),
    '7': ('No known copyright restrictions', 'https://www.flickr.com/commons/usage/', EXCLUDED, 'A statement of uncertainty, not a grant of permission.'),
    '8': ('United States Government Work', 'http://www.usa.gov/copyright.shtml', EXCLUDED, 'Status outside the United States is uncertain.'),
    '9': ('CC0 1.0', 'https://creativecommons.org/publicdomain/zero/1.0/', CAMPAIGN_ELIGIBLE, 'No attribution required; ATIA still credits the photographer.'),
    '10': ('Public Domain Mark 1.0', 'https://creativecommons.org/publicdomain/mark/1.0/', EXCLUDED, 'A label applied to a work, not a grant of permission from the owner.'),
    '11': ('CC BY 4.0', _BY + 'by/4.0/', CAMPAIGN_ELIGIBLE, 'Attribution required.'),
    '12': ('CC BY-SA 4.0', _BY + 'by-sa/4.0/', CAMPAIGN_ELIGIBLE, 'Attribution required; adaptations must share alike.'),
    '13': ('CC BY-ND 4.0', _BY + 'by-nd/4.0/', EXCLUDED, 'No derivatives; campaign crops and overlays are adaptations.'),
    '14': ('CC BY-NC 4.0', _BY + 'by-nc/4.0/', EXCLUDED, 'Non-commercial only; marketing is commercial use.'),
    '15': ('CC BY-NC-ND 4.0', _BY + 'by-nc-nd/4.0/', EXCLUDED, 'Non-commercial and no derivatives.'),
    '16': ('CC BY-NC-SA 4.0', _BY + 'by-nc-sa/4.0/', EXCLUDED, 'Non-commercial only; marketing is commercial use.'),
}


def interpret(license_id):
    """Every unrecognized or missing ID is UNKNOWN, which never permits campaign use."""
    key = None if license_id is None else str(license_id).strip()
    if key not in LICENCES:
        return {'license_id': key or None, 'name': None, 'url': None, 'campaign_status': UNKNOWN,
                'campaign_eligible': False, 'reason': 'Licence is missing or not recognized.'}
    name, url, status, reason = LICENCES[key]
    return {'license_id': key, 'name': name, 'url': url, 'campaign_status': status,
            'campaign_eligible': status == CAMPAIGN_ELIGIBLE, 'reason': reason}


def interpret_recorded(license_id, license_url=None):
    """A licence stored on a row: its ID when known, otherwise an exact match on its URL."""
    if license_id is not None and str(license_id).strip() in LICENCES:
        return interpret(license_id)
    url = (license_url or '').rstrip('/') + '/'
    return interpret(next((key for key, value in LICENCES.items() if value[1] == url), None))


def attribution_text(title, photographer, licence, photo_url):
    """A ready-to-use credit line built only from recorded values."""
    credit = f'“{title}”' if title else 'Untitled photograph'
    credit += f' by {photographer}' if photographer else ' (photographer not recorded)'
    details = [licence.get('name') or 'licence unknown']
    if photo_url:
        details.append(photo_url)
    return credit + ' · ' + ' · '.join(details)
