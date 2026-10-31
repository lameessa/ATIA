"""Offline: a mocked model and synthetic records. No paid request is possible here."""
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4
from fastapi.testclient import TestClient
import pytest
from atia.agents.contracts import Limits
from atia.api.campaign_workflow import outcome_message
from atia.api.dashboard import create_app
from atia.api.media import FlickrMedia
from atia.destinations.storage import DestinationStore
from atia.intelligence.signals import build_signals
from atia.opportunities.curate import build_opportunities
from atia.opportunities.generate import assess_decision, build_dossier, estimate, guard_decision, next_opportunity, recover_rejected, review_validation, run_opportunity
from atia.opportunities.images import find_images, relevant, review_image
from atia.opportunities.store import OpportunityStore
from atia.moderation.display import can_display
from atia.storage.sqlite import PhotoStore
from display_fixtures import approve
from test_intelligence import Client, Fetcher, add, restore

HEADERS = {'X-ATIA-Action': 'confirmed'}


def release(db, photo_id):
    """Evidence clearance for a live test photo, as the moderation workflow would record it."""
    with db:
        db.execute("UPDATE photo_moderation SET status='approved', relevance='relevant', safety='pass', reviewer='Test', reviewed_at='now' WHERE photo_id=?", (photo_id,))
B = lambda en='English copy', ar='نص عربي': {'en': en, 'ar': ar}
CONFIG = {'opportunities': [
    {'slug': 'qassim', 'signal_kind': 'regional_experience', 'signal_key': 'qassim:agricultural_tourism', 'angle': B('Date-palm country', 'موطن النخيل'),
     'image_search': {'queries': ['palm'], 'bbox': '42,25,45,27', 'must_match': ['palm', 'نخل']}},
    {'slug': 'namar', 'signal_kind': 'named_destination', 'signal_key': 'wadi namar', 'angle': B('Green escape', 'متنفس أخضر')},
    {'slug': 'absent', 'signal_kind': 'named_destination', 'signal_key': 'no such place', 'angle': B()}]}


def campaign():
    return {'campaign_name': B('Palm Country', 'بلاد النخيل'), 'central_concept': B(), 'objectives': [B()], 'target_audience': B(), 'audience_rationale_hypothesis': B(), 'positioning': B(),
            'opportunity_hypothesis': B(), 'key_messages': [B()], 'creative_direction': B(),
            'social_posts': [{'post_id': 'p1', 'channel': 'Instagram', 'caption': B('Caption one', 'تعليق أول')}, {'post_id': 'p2', 'channel': 'X', 'caption': B('Caption two', 'تعليق ثان')}], 'suggested_channels': ['Instagram', 'X'],
            'publishing_schedule': [{'post_id': 'p1', 'days_after_human_approved_launch': 0, 'local_time': '18:30', 'timezone': 'Asia/Riyadh', 'channel': 'Instagram', 'activity': B()},
                                    {'post_id': 'p2', 'days_after_human_approved_launch': 3, 'local_time': '19:00', 'timezone': 'Asia/Riyadh', 'channel': 'X', 'activity': B()}],
            'kpis_and_measurement': [{'metric': B(), 'measurement_plan': B(), 'baseline': 'UNMEASURED', 'proposed_target_hypothesis': B()}], 'risks_uncertainties_validation': [B()]}


def decision(**changes):
    return {'decision': 'CREATE', 'recommendation': 'Evidence supports an agricultural angle.', 'marketing_angle': 'Date-palm country', 'claims': [{'claim': 'Photographers share date farms.', 'evidence_refs': ['photo:c1']}],
            'uncertainties': ['Farm access is unverified.'], 'next_actions': ['Verify visits.'], 'campaign': campaign(), **changes}


def model(value):
    client = Mock()
    usage = SimpleNamespace(input_tokens=1000, output_tokens=1500, model_dump=lambda: {'input_tokens': 1000, 'output_tokens': 1500})
    client.responses.create.return_value = SimpleNamespace(id='resp', status='completed', usage=usage, output_text=value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
    return client


def seed(db):
    add(db, 'a1', 'Namar Valley', owner='o1', license_id='9', latitude=24.57, longitude=46.68, location={'accuracy': '16', 'region': {'_content': 'الرياض'}})
    add(db, 'a2', 'وادي نمار', owner='o2')
    add(db, 'c1', 'Date farm in AlQassim', owner='o4', location={'region': {'_content': 'القصيم'}})
    add(db, 'c2', 'Palm - نخلة', owner='o5', tags=['Qassim'])
    db.commit()


@pytest.fixture
def ready(tmp_path):
    path = tmp_path / 'db.sqlite3'
    config = tmp_path / 'config.json'
    config.write_text(json.dumps(CONFIG, ensure_ascii=False))
    with PhotoStore(str(path)) as store:
        DestinationStore(store)
        seed(store.connection)
        restore(store, tmp_path, Client({'a1': '9'}))
        build_signals(store.connection)
        report = build_opportunities(store.connection, config)
    return SimpleNamespace(path=path, tmp=tmp_path, report=report)


def open_store(ready):
    return PhotoStore(str(ready.path))


def test_opportunities_come_only_from_real_signals_and_label_evidence(ready):
    assert report_ids(ready) == ['qassim', 'namar'] and ready.report['missing_signals'] == ['absent']
    with open_store(ready) as store:
        qassim = OpportunityStore(store.connection).opportunity('qassim')
    assert qassim['identity'] is None and qassim['evidence_label'] == 'Moderate evidence' and qassim['photo_ids'] == ['c1', 'c2']


def report_ids(ready):
    return [o['id'] for o in ready.report['opportunities']]


def test_regional_opportunity_needs_no_verified_entity_and_saves_a_text_only_draft(ready):
    with open_store(ready) as store:
        result = run_opportunity(store, 'qassim', Limits(), model(decision()))
        saved = OpportunityStore(store.connection).campaigns()
    assert result['errors'] == [] and result['campaign_id'].startswith('oppcampaign-')
    assert saved[0]['campaign']['destination']['entity_id'] is None
    assert saved[0]['campaign']['destination']['name']['en'] == 'Agricultural and farm tourism in Al Qassim'
    assert 'approved_photo_assets' not in saved[0]['campaign']


def test_model_receives_real_evidence_and_no_image_control(ready):
    client = model(decision())
    with open_store(ready) as store:
        run_opportunity(store, 'qassim', Limits(), client)
    sent = client.responses.create.call_args.kwargs
    assert 'Date farm in AlQassim' in sent['input'][0]['content'] and 'approved_photo_assets' not in json.dumps(sent['text'])
    assert client.responses.create.call_count == 1


@pytest.mark.parametrize('bad,message', [
    (lambda d: d['campaign']['central_concept'].update(en='A hidden gem for all'), 'unsupported claim'),
    (lambda d: d['campaign']['positioning'].update(en='An overlooked region'), 'unsupported claim'),
    (lambda d: d['campaign']['central_concept'].update(ar='جوهرة مخفية في القصيم'), 'unsupported claim'),
    (lambda d: d['campaign']['central_concept'].update(en='Home to 4500 farms'), 'figure'),
    (lambda d: d['campaign']['central_concept'].update(en='Up by 40% this year'), 'figure'),
    (lambda d: d['campaign']['central_concept'].update(ar='English only'), 'English and Arabic'),
    (lambda d: d['claims'][0].update(evidence_refs=['photo:invented']), 'not supplied'),
    (lambda d: d.update(claims=[]), 'cited claims'),
    (lambda d: d.update(uncertainties=[]), 'uncertainties'),
    (lambda d: d['campaign']['social_posts'].append({'post_id': 'p3', 'channel': 'X', 'caption': B()}), 'schedule entry'),
    (lambda d: d['campaign']['publishing_schedule'][0].update(local_time='evening'), 'HH:MM'),
    (lambda d: d['campaign']['publishing_schedule'][0].update(channel='TikTok'), 'matching|match'),
    (lambda d: d.update(decision='INVESTIGATE'), 'Only CREATE'),
    (lambda d: d['campaign']['opportunity_hypothesis'].update(en='There is growing interest in farms'), 'growing interest'),
    (lambda d: d['campaign']['opportunity_hypothesis'].update(ar='يوجد اهتمام متزايد بالسياحة الزراعية'), 'اهتمام متزايد'),
    (lambda d: d['campaign']['central_concept'].update(en='The most popular farms'), 'popular'),
    (lambda d: d['campaign']['key_messages'][0].update(en='Enjoy farm tours in Al Qassim'), 'unverified activity: tour'),
    (lambda d: d['campaign']['key_messages'][0].update(ar='جولات في المزارع'), 'unverified activity: tour'),
    (lambda d: d['campaign']['objectives'][0].update(en='Encourage harvest activities'), 'harvest activity'),
    (lambda d: d['campaign']['creative_direction'].update(en='Show a date tasting'), 'tasting'),
    (lambda d: d['claims'][0].update(claim='Engagement metrics indicate interest in date farming'), 'engagement as evidence'),
    (lambda d: d['claims'][0].update(claim='High view counts show strong appeal'), 'engagement as evidence'),
    (lambda d: d.update(recommendation='Target rising demand'), 'demand|rising'),
])
def test_guard_rejects_unsafe_drafts(ready, bad, message):
    value = decision()
    bad(value)
    with open_store(ready) as store:
        dossier = build_dossier(store.connection, OpportunityStore(store.connection).opportunity('qassim'))
    with pytest.raises(ValueError, match=message):
        guard_decision(value, dossier)


def test_guard_does_not_require_official_hidden_gem_wording_or_high_engagement(ready):
    with open_store(ready) as store:
        dossier = build_dossier(store.connection, OpportunityStore(store.connection).opportunity('qassim'))
    assert dossier['stored_research'] == [] and guard_decision(decision(), dossier)['decision'] == 'CREATE'


def test_blocked_output_is_kept_for_correction_and_malformed_output_saves_nothing(ready):
    bad = decision()
    bad['campaign']['central_concept']['en'] = 'A hidden gem'
    with open_store(ready) as store:
        client = model(bad)
        result = run_opportunity(store, 'qassim', Limits(), client)
        assert result['campaign_id'] and 'hidden gem' in result['validation']['blocking'][0] and client.responses.create.call_count == 1
    with open_store(ready) as store:
        client = model('{"not json')
        result = run_opportunity(store, 'rijal', Limits(), client) if OpportunityStore(store.connection).opportunity('rijal') else None
        if result:
            assert result['errors'] and result['campaign_id'] is None and result['decision']['decision'] == 'INVESTIGATE'
            assert client.responses.create.call_count == 1


def test_draft_without_claims_is_visible_but_blocked(ready):
    with open_store(ready) as store:
        result = run_opportunity(store, 'qassim', Limits(), model(decision(claims=[])))
        campaign = OpportunityStore(store.connection).campaigns()[0]
        assert result['campaign_id'] == campaign['campaign_id'] and result['errors'] == []
        found = review_validation(campaign['campaign'], campaign['evidence'])
    assert found['state'] == 'NEEDS_CORRECTION' and 'CREATE needs cited claims' in found['blocking']


def test_accepted_output_is_not_duplicated_as_rejected(ready):
    with open_store(ready) as store:
        assert 'rejected_output' not in run_opportunity(store, 'qassim', Limits(), model(decision()))


def test_prompt_requires_top_level_claims_and_uncertainties():
    from atia.opportunities.generate import PROMPT
    assert 'at least 2 entries in claims' in PROMPT and 'at least 1 entry in uncertainties' in PROMPT


def test_incomplete_response_is_not_saved(ready):
    client = model(decision())
    client.responses.create.return_value.status = 'incomplete'
    with open_store(ready) as store:
        assert run_opportunity(store, 'qassim', Limits(), client)['campaign_id'] is None


def test_investigate_is_a_valid_outcome_without_a_draft(ready):
    with open_store(ready) as store:
        result = run_opportunity(store, 'qassim', Limits(), model(decision(decision='INVESTIGATE', campaign=None)))
    assert result['errors'] == [] and result['campaign_id'] is None


def test_existing_draft_makes_no_second_paid_request(ready):
    with open_store(ready) as store:
        first = run_opportunity(store, 'qassim', Limits(), model(decision()))
        client = model(decision())
        second = run_opportunity(store, 'qassim', Limits(), client)
    assert client.responses.create.call_count == 0 and second['campaign_id'] == first['campaign_id'] and second['estimated_api_cost_usd'] == 0


def test_budget_is_enforced_before_any_request(ready):
    client = model(decision())
    with open_store(ready) as store:
        result = run_opportunity(store, 'qassim', Limits(run_budget_usd=.0001), client)
    assert client.responses.create.call_count == 0 and result['campaign_id'] is None and result['errors']


def test_spend_is_recorded_in_the_shared_ledger(ready):
    with open_store(ready) as store:
        run_opportunity(store, 'qassim', Limits(), model(decision()))
        charged = store.connection.execute('SELECT sum(charged_usd) FROM agent_discovery_requests').fetchone()[0]
    assert charged == pytest.approx((1000 * .15 + 1500 * .6) / 1_000_000)


def test_autonomous_choice_prefers_stronger_evidence_and_skips_drafted(ready):
    with open_store(ready) as store:
        assert next_opportunity(store.connection)['opportunity_id'] == 'qassim'
        run_opportunity(store, 'qassim', Limits(), model(decision()))
        assert next_opportunity(store.connection)['opportunity_id'] == 'namar'


def test_estimate_is_free_and_bounded(ready):
    with open_store(ready) as store:
        value = estimate(build_dossier(store.connection, OpportunityStore(store.connection).opportunity('qassim')), Limits())
    assert 0 < value['upper_bound_usd'] < Limits().run_budget_usd


# Image search
class SearchClient(Client):
    def __init__(self, results, not_saudi=(), licences=None):
        super().__init__(licences or {})
        self.results, self.not_saudi, self.searches = results, set(not_saudi), []

    def call(self, method, photo_id=None, **params):
        if method == 'flickr.photos.search':
            self.searches.append(params)
            return {'photos': {'photo': self.results}}
        return super().call(method, photo_id=photo_id, **params)

    def verify_location(self, photo_id, country):
        return None if photo_id in self.not_saudi else {'country': {'woeid': country, '_content': 'Saudi Arabia'}}


def result(photo_id, title='Date palms', owner='x', license_id='4'):
    return {'id': photo_id, 'title': title, 'owner': owner, 'license': license_id, 'tags': '', 'latitude': '26', 'longitude': '44', 'description': {'_content': ''}}


def test_search_requests_only_campaign_licences_and_safe_photos(ready):
    client = SearchClient([])
    with open_store(ready) as store:
        find_images(store, client, fetcher=Fetcher(ready.tmp), opportunity_id='qassim')
    assert client.searches[0]['license'] == '4,5,9,11,12' and client.searches[0]['safe_search'] == 1 and client.searches[0]['bbox']


def test_candidates_stay_hidden_until_accepted_and_filters_apply(ready):
    client = SearchClient([result('n1', 'Date palms'), result('n2', 'A car park'), result('n3', 'Palm in Oman'), result('n4', 'Palm grove', license_id='4'), result('c1', 'Date farm')], not_saudi=['n3'], licences={'n1': '4', 'n4': '0'})
    from atia.moderation.policy import allowed
    with open_store(ready) as store:
        report = find_images(store, client, fetcher=Fetcher(ready.tmp), opportunity_id='qassim')['qassim']
        assert [c['photo_id'] for c in report['candidates']] == ['n1']
        assert (report['off_topic'], report['not_saudi'], report['failed'], report['already_in_archive']) == (1, 1, 1, 1)
        assert allowed(store.connection, 'flickr_live', 'n1') is False
        assert review_image(store.connection, 'qassim', 'n1', True, 'Reviewer', 'On topic')['displayable'] is False
        assert allowed(store.connection, 'flickr_live', 'n1') is False and not can_display(store.connection, 'flickr_live', 'n1')
        assert OpportunityStore(store.connection).accepted_images('qassim') == [{'source': 'flickr_live', 'photo_id': 'n1'}]


def test_review_requires_reason_and_rechecks_licence(ready):
    with open_store(ready) as store:
        find_images(store, SearchClient([result('n1')], licences={'n1': '4'}), fetcher=Fetcher(ready.tmp), opportunity_id='qassim')
        with pytest.raises(ValueError):
            review_image(store.connection, 'qassim', 'n1', True, '', '')
        with store.connection:
            store.connection.execute("UPDATE photo_flickr_status SET current_license_id='0' WHERE photo_id='n1'")
        with pytest.raises(ValueError, match='Licence'):
            review_image(store.connection, 'qassim', 'n1', True, 'R', 'ok')


def test_relevance_uses_title_tags_and_description():
    assert relevant({'title': 'نخيل القصيم'}, ['نخيل']) and relevant({'title': 'x', 'tags': 'farm'}, ['farm'])
    assert not relevant({'title': 'Update', 'tags': 'candidate'}, ['date'])


# Whole workflow through the API
def run_and_wait(client, body):
    import time
    job = client.post('/api/campaign-requests', headers=HEADERS, json={'confirmed': True, 'idempotency_key': str(uuid4()), **body})
    assert job.status_code == 202
    for _ in range(100):
        current = client.get('/api/campaign-requests/' + job.json()['job_id']).json()
        if current['status'] not in ('queued', 'running'):
            return current
        time.sleep(.02)
    raise AssertionError('Job did not finish')


def test_opportunity_to_studio_to_approval_to_calendar(ready):
    def runner(store, opportunity_id, limits, progress):
        return run_opportunity(store, opportunity_id, limits, model(decision()), progress)
    with TestClient(create_app(str(ready.path), opportunity_runner=runner)) as client:
        snapshot = client.get('/api/workspace').json()
        assert [o['id'] for o in snapshot['opportunities']] == ['qassim', 'namar'] and snapshot['campaigns'] == []
        assert client.post('/api/campaign-requests', json={'opportunity_id': 'qassim', 'confirmed': True, 'idempotency_key': str(uuid4())}).status_code == 403
        job = run_and_wait(client, {'opportunity_id': 'qassim'})
        assert job['status'] == 'completed' and job['campaign_id']
        snapshot = client.get('/api/workspace').json()
        draft = snapshot['campaigns'][0]
        assert draft['status'] == 'PENDING_APPROVAL' and draft['content']['campaign_name']['ar'] == 'بلاد النخيل' and draft['media'] == [] and draft['media_validation_required'] is False
        assert {s['publisher'] for s in draft['sources']} >= {'Flickr · Name o4'} and snapshot['opportunities'][0]['campaign_id'] == draft['id']
        assert client.get('/api/calendar').json()['entries'] == []
        existing = client.post('/api/campaign-requests', headers=HEADERS, json={'opportunity_id': 'qassim', 'confirmed': True, 'idempotency_key': str(uuid4())})
        assert existing.json()['status'] == 'existing'
        edited = client.post(f"/api/campaigns/{draft['id']}/edit", headers=HEADERS, json={'revision': 0, 'editor': 'R', 'confirmed': True, 'title': B('Edited Palms', 'نخيل معدل'), 'publishing_dates': {'p1': '2026-12-01'}})
        assert edited.status_code == 200 and edited.json()['revision'] == 1
        assert client.post(f"/api/campaigns/{draft['id']}/review", headers=HEADERS, json={'decision': 'APPROVED', 'revision': 0, 'confirmed': True}).status_code == 409
        assert client.post(f"/api/campaigns/{draft['id']}/review", headers=HEADERS, json={'decision': 'APPROVED', 'revision': 1, 'reviewer': 'R', 'confirmed': True}).status_code == 200
        entries = client.get('/api/calendar').json()['entries']
        assert {e['post_id']: e['proposed_date'] for e in entries} == {'p1': '2026-12-01', 'p2': None} and entries[0]['campaign_name']['en'] == 'Edited Palms'
        assert client.get('/api/workspace').json()['campaigns'][0]['status'] == 'APPROVED'


def test_launch_date_turns_relative_days_into_calendar_dates(ready):
    def runner(store, opportunity_id, limits, progress):
        return run_opportunity(store, opportunity_id, limits, model(decision()), progress)
    with TestClient(create_app(str(ready.path), opportunity_runner=runner)) as client:
        draft_id = run_and_wait(client, {'opportunity_id': 'qassim'})['campaign_id']
        assert client.post(f'/api/campaigns/{draft_id}/review', headers=HEADERS, json={'decision': 'APPROVED', 'launch_date': '2026-11-10', 'confirmed': True}).status_code == 200
        entries = client.get('/api/calendar').json()['entries']
    assert {e['post_id']: e['proposed_date'] for e in entries} == {'p1': '2026-11-10', 'p2': '2026-11-13'}


def test_rejected_draft_stays_off_the_calendar_and_can_be_retried(ready):
    def runner(store, opportunity_id, limits, progress):
        return run_opportunity(store, opportunity_id, limits, model(decision()), progress)
    with TestClient(create_app(str(ready.path), opportunity_runner=runner)) as client:
        draft_id = run_and_wait(client, {'opportunity_id': 'qassim'})['campaign_id']
        assert client.post(f'/api/campaigns/{draft_id}/review', headers=HEADERS, json={'decision': 'REJECTED', 'confirmed': True}).status_code == 200
        assert client.get('/api/calendar').json()['entries'] == []
        assert client.get('/api/workspace').json()['opportunities'][0]['campaign_id'] is None


def test_no_target_request_autonomously_picks_a_curated_opportunity(ready):
    seen = []
    def runner(store, opportunity_id, limits, progress):
        seen.append(opportunity_id)
        return run_opportunity(store, opportunity_id, limits, model(decision()), progress)
    with TestClient(create_app(str(ready.path), opportunity_runner=runner)) as client:
        run_and_wait(client, {})
    assert seen == ['qassim']


def test_unknown_opportunity_is_refused_without_a_job(ready):
    with TestClient(create_app(str(ready.path))) as client:
        response = client.post('/api/campaign-requests', headers=HEADERS, json={'opportunity_id': 'made-up', 'confirmed': True, 'idempotency_key': str(uuid4())})
        assert response.status_code == 409 and client.get('/api/campaign-requests').json()['jobs'] == []


def test_only_licensed_images_attach_to_a_campaign(ready):
    with TestClient(create_app(str(ready.path))) as client:
        namar = next(o for o in client.get('/api/workspace').json()['opportunities'] if o['id'] == 'namar')
        assert namar['licensed_images'] == 0 and namar['media'] is None and namar['gallery'] == []
        assert namar['evidence']['photo_count'] == 2 and len(namar['evidence_photos']) == 2
    with open_store(ready) as store:
        approve(store.connection, 'afaq_historical', 'a1', '9', keep_status=True)
    with TestClient(create_app(str(ready.path))) as client:
        namar = next(o for o in client.get('/api/workspace').json()['opportunities'] if o['id'] == 'namar')
    assert namar['licensed_images'] == 1 and namar['media']['photo_id'] == 'a1' and namar['media']['rights_status'] == 'reusable_with_attribution'
    assert [m['photo_id'] for m in namar['gallery']] == ['a1']


def test_image_loses_campaign_use_if_flickr_licence_changes_after_selection(ready):
    with open_store(ready) as store:
        with store.connection:
            store.connection.execute("UPDATE photo_flickr_status SET current_license_id='0' WHERE photo_id='a1'")
    with TestClient(create_app(str(ready.path))) as client:
        namar = next(o for o in client.get('/api/workspace').json()['opportunities'] if o['id'] == 'namar')
    assert namar['licensed_images'] == 0 and all(m['rights_status'] == 'permission_not_verified' for m in namar['gallery'])


def test_searched_photo_is_credited_by_name_not_flickr_id(ready):
    with open_store(ready) as store:
        find_images(store, SearchClient([{**result('n1'), 'ownername': 'Search Name'}], licences={'n1': '4'}), fetcher=Fetcher(ready.tmp), opportunity_id='qassim')
        review_image(store.connection, 'qassim', 'n1', True, 'Reviewer', 'On topic')
        release(store.connection, 'n1')
        approve(store.connection, 'flickr_live', 'n1', '4', keep_status=True)
        asset = FlickrMedia(store.connection).asset('flickr_live', 'n1')
        assert asset['attribution'] == 'Current Owner' and 'by Current Owner' in asset['attribution_text']
        with store.connection:
            store.connection.execute("UPDATE photo_flickr_status SET owner_name=NULL WHERE photo_id='n1'")
        assert FlickrMedia(store.connection).asset('flickr_live', 'n1')['attribution'] == 'Search Name'


def test_guard_allows_activities_a_record_shows_and_risks_that_name_them(ready):
    with open_store(ready) as store:
        dossier = build_dossier(store.connection, OpportunityStore(store.connection).opportunity('qassim'))
    named_risk = decision()
    named_risk['campaign']['risks_uncertainties_validation'][0]['en'] = 'Confirm whether farm tours exist before mentioning them.'
    assert guard_decision(named_risk, dossier)['decision'] == 'CREATE'
    copy = decision()
    copy['campaign']['key_messages'][0]['en'] = 'Guided tour of the groves'
    dossier['photos'][0]['description'] = 'A guided tour of the groves'
    assert guard_decision(copy, dossier)['decision'] == 'CREATE'


def test_ordinary_words_do_not_trip_the_language_checks(ready):
    with open_store(ready) as store:
        dossier = build_dossier(store.connection, OpportunityStore(store.connection).opportunity('qassim'))
    value = decision()
    value['campaign']['key_messages'][0]['en'] = 'Palm groves, seen by touring photographers. Rewards a closer look, misleading no one.'
    value['claims'][0]['claim'] = 'Three photographers shared date farm and palm photographs.'
    assert guard_decision(value, dossier)['decision'] == 'CREATE'


def full_edit(draft_id, revision=0, **extra):
    return {'revision': revision, 'editor': 'Editor', 'confirmed': True, **extra}


def test_reviewer_sees_claims_with_sources_and_uncertainties(ready):
    def runner(store, opportunity_id, limits, progress):
        return run_opportunity(store, opportunity_id, limits, model(decision()), progress)
    with TestClient(create_app(str(ready.path), opportunity_runner=runner)) as client:
        run_and_wait(client, {'opportunity_id': 'qassim'})
        review = client.get('/api/workspace').json()['campaigns'][0]['evidence_review']
    assert review['claims'][0]['claim'] == 'Photographers share date farms.'
    assert review['claims'][0]['sources'][0]['publisher'] == 'Flickr · Name o4' and review['claims'][0]['sources'][0]['url'].endswith('/c1/')
    assert review['uncertainties'] == ['Farm access is unverified.'] and review['edited'] is False


def test_all_copy_is_editable_and_the_original_ai_draft_is_preserved(ready):
    def runner(store, opportunity_id, limits, progress):
        return run_opportunity(store, opportunity_id, limits, model(decision()), progress)
    with TestClient(create_app(str(ready.path), opportunity_runner=runner)) as client:
        draft_id = run_and_wait(client, {'opportunity_id': 'qassim'})['campaign_id']
        body = full_edit(draft_id, positioning=B('New position', 'تموضع جديد'), opportunity_hypothesis=B('New hypothesis', 'فرضية جديدة'), target_audience=B('New audience', 'جمهور جديد'),
                         audience_rationale_hypothesis=B('New why', 'سبب جديد'), objectives=[B('New objective', 'هدف جديد')], key_messages=[B('New message', 'رسالة جديدة')],
                         risks_uncertainties_validation=[B('New risk', 'مخاطر جديدة')], schedule_activities={'p1': B('New activity', 'نشاط جديد')},
                         kpis=[{'metric': B('M', 'مقياس'), 'measurement_plan': B('P', 'خطة'), 'proposed_target_hypothesis': B('T', 'هدف')}],
                         evidence={'recommendation': 'Corrected.', 'claims': [{'claim': 'Corrected claim.', 'evidence_refs': ['photo:c1']}], 'uncertainties': ['Corrected uncertainty.']})
        assert client.post(f'/api/campaigns/{draft_id}/edit', headers=HEADERS, json=body).status_code == 200
        draft = client.get('/api/workspace').json()['campaigns'][0]
        content = draft['content']
        assert content['positioning']['en'] == 'New position' and content['opportunity_hypothesis']['ar'] == 'فرضية جديدة' and content['key_messages'] == [B('New message', 'رسالة جديدة')]
        assert content['publishing_schedule'][0]['activity']['en'] == 'New activity' and content['kpis_and_measurement'][0]['baseline'] == 'UNMEASURED'
        assert draft['edited_by'] == 'Editor' and draft['evidence_review']['edited'] is True
        assert draft['evidence_review']['claims'][0]['claim'] == 'Corrected claim.' and draft['evidence_review']['original']['claims'] == ['Photographers share date farms.']
    with open_store(ready) as store:
        original = OpportunityStore(store.connection).campaigns()[0]
    assert original['campaign']['positioning'] == B() and original['evidence']['claims'][0]['claim'] == 'Photographers share date farms.'


def test_edited_claims_must_cite_supplied_evidence_and_arabic_stays_required(ready):
    def runner(store, opportunity_id, limits, progress):
        return run_opportunity(store, opportunity_id, limits, model(decision()), progress)
    with TestClient(create_app(str(ready.path), opportunity_runner=runner)) as client:
        draft_id = run_and_wait(client, {'opportunity_id': 'qassim'})['campaign_id']
        invented = full_edit(draft_id, evidence={'recommendation': 'x', 'claims': [{'claim': 'x', 'evidence_refs': ['photo:invented']}], 'uncertainties': ['x']})
        assert client.post(f'/api/campaigns/{draft_id}/edit', headers=HEADERS, json=invented).status_code == 422
        assert client.post(f'/api/campaigns/{draft_id}/edit', headers=HEADERS, json=full_edit(draft_id, positioning={'en': 'x', 'ar': 'english'})).status_code == 422
        assert client.post(f'/api/campaigns/{draft_id}/edit', headers=HEADERS, json=full_edit(draft_id, schedule_activities={'nope': B()})).status_code == 422


def test_first_posts_in_arabic_is_not_a_superlative(ready):
    with open_store(ready) as store:
        dossier = build_dossier(store.connection, OpportunityStore(store.connection).opportunity('qassim'))
    value = decision()
    value['campaign']['kpis_and_measurement'][0]['proposed_target_hypothesis']['ar'] = 'يحدد الهدف بعد قياس المنشورات الأولى.'
    assert guard_decision(value, dossier)['decision'] == 'CREATE'


def test_review_port_is_allowed_only_when_set_and_only_locally(ready, monkeypatch):
    body = {'decision': 'REJECTED', 'confirmed': True}
    origin = {**HEADERS, 'Origin': 'http://127.0.0.1:5174'}
    with TestClient(create_app(str(ready.path))) as client:
        assert client.post('/api/campaigns/none/review', headers=origin, json=body).status_code == 403
    monkeypatch.setenv('ATIA_REVIEW_ORIGINS', 'http://127.0.0.1:5174')
    with TestClient(create_app(str(ready.path))) as client:
        assert client.post('/api/campaigns/none/review', headers=origin, json=body).status_code == 404
        assert client.post('/api/campaigns/none/review', headers={**HEADERS, 'Origin': 'http://127.0.0.1:9999'}, json=body).status_code == 403
    monkeypatch.setenv('ATIA_REVIEW_ORIGINS', 'https://evil.example')
    with pytest.raises(ValueError, match='local'):
        create_app(str(ready.path))



def test_missing_key_stops_before_a_job_or_budget_is_used(ready, monkeypatch):
    """The real path with no injected runner: nothing is queued, reserved or charged."""
    monkeypatch.setenv('OPENAI_API_KEY', '')
    with TestClient(create_app(str(ready.path))) as client:
        response = client.post('/api/campaign-requests', headers=HEADERS, json={'opportunity_id': 'qassim', 'confirmed': True, 'idempotency_key': str(uuid4())})
        assert response.status_code == 503 and 'requires configuration' in response.json()['detail']
        assert client.get('/api/agent/policy').json()['openai_configured'] is False
        assert client.get('/api/campaign-requests').json()['jobs'] == []
    with PhotoStore(str(ready.path)) as store:
        assert not store.connection.execute("SELECT 1 FROM sqlite_master WHERE name='agent_discovery_requests'").fetchone() or store.connection.execute('SELECT count(*) FROM agent_discovery_requests').fetchone()[0] == 0


def test_generator_without_a_key_reserves_nothing(ready, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', '')
    with PhotoStore(str(ready.path)) as store:
        result = run_opportunity(store, 'qassim')
        assert result['errors'][0].startswith('Not sent: OPENAI_API_KEY') and result['campaign_id'] is None
        assert store.connection.execute('SELECT count(*) FROM agent_discovery_requests').fetchone()[0] == 0


@pytest.mark.parametrize('errors,decision,expected', [
    (['Not sent: OPENAI_API_KEY is missing'], 'INVESTIGATE', 'no OpenAI request was sent'),
    (['Draft rejected: Draft asserts an unsupported claim: popular'], 'INVESTIGATE', "ATIA's checks rejected the AI draft"),
    (['OpenAI request failed (AuthenticationError, status=401)'], 'INVESTIGATE', 'rejected the API key'),
    (['OpenAI request failed (RateLimitError, status=429)'], 'INVESTIGATE', 'rate limit'),
    (['OpenAI request failed (APITimeoutError, status=None)'], 'INVESTIGATE', 'may still be billed'),
    ([], 'INVESTIGATE', 'The model did not draft a campaign: Evidence is weak'),
])
def test_a_failed_generation_says_what_stopped_it(errors, decision, expected):
    assert expected in outcome_message({'errors': errors, 'decision': {'recommendation': 'Evidence is weak'}}, None, decision)


@pytest.mark.parametrize('change,warning', [
    (lambda d: d['campaign']['positioning'].update(en='Al Qassim as a premier getaway'), 'premier'),
    (lambda d: d['campaign']['positioning'].update(ar='القصيم كوجهة رائدة'), 'رائدة'),
    (lambda d: d['campaign']['key_messages'][0].update(en='Join us this season'), 'join us'),
    (lambda d: d['campaign']['central_concept'].update(en='A popular walk among the palms'), 'popular'),
    (lambda d: d['campaign']['kpis_and_measurement'][0]['proposed_target_hypothesis'].update(en='Reach a 5% rate'), '5%'),
])
def test_promotional_wording_and_proposed_targets_only_warn(ready, change, warning):
    value = decision()
    change(value)
    with open_store(ready) as store:
        dossier = build_dossier(store.connection, OpportunityStore(store.connection).opportunity('qassim'))
    findings = assess_decision(value, dossier)
    assert findings['blocking'] == [] and any(warning in w for w in findings['warnings'])


@pytest.mark.parametrize('change,problem', [
    (lambda d: d['claims'][0].update(claim='These parks are popular among families'), 'popular'),
    (lambda d: d['campaign']['objectives'][0].update(en='Serve 40% of visitors'), '40%'),
    (lambda d: d['campaign']['key_messages'][0].update(en='Temporary marriage offers'), 'Unsafe'),
])
def test_invented_facts_and_unsafe_content_still_block(ready, change, problem):
    value = decision()
    change(value)
    with open_store(ready) as store:
        dossier = build_dossier(store.connection, OpportunityStore(store.connection).opportunity('qassim'))
    assert any(problem in b for b in assess_decision(value, dossier)['blocking'])


def blocked_decision():
    value = decision()
    value['claims'][0]['claim'] = 'There is growing interest in farms'
    return value


def test_blocked_draft_is_kept_but_cannot_be_approved_until_corrected(ready):
    def runner(store, opportunity_id, limits, progress):
        return run_opportunity(store, opportunity_id, limits, model(blocked_decision()), progress)
    with TestClient(create_app(str(ready.path), opportunity_runner=runner)) as client:
        job = run_and_wait(client, {'opportunity_id': 'qassim'})
        assert job['campaign_id']
        draft = client.get('/api/workspace').json()['campaigns'][0]
        assert draft['validation']['state'] == 'NEEDS_CORRECTION' and 'growing interest' in draft['validation']['blocking'][0]
        approve = {'decision': 'APPROVED', 'revision': 0, 'launch_date': '2026-11-10', 'confirmed': True}
        assert client.post(f"/api/campaigns/{draft['id']}/review", headers=HEADERS, json=approve).status_code == 409
        assert client.get('/api/calendar').json()['entries'] == []
        review = draft['evidence_review']
        fixed = [{**c, 'claim': 'Three photographers shared date farm photographs.'} for c in review['raw_claims']]
        edit = client.post(f"/api/campaigns/{draft['id']}/edit", headers=HEADERS, json={**full_edit(draft['id']), 'evidence': {'recommendation': review['recommendation'], 'claims': fixed, 'uncertainties': review['uncertainties']}})
        assert edit.status_code == 200
        draft = client.get('/api/workspace').json()['campaigns'][0]
        assert draft['validation']['blocking'] == []
        assert client.post(f"/api/campaigns/{draft['id']}/review", headers=HEADERS, json={**approve, 'revision': 1}).status_code == 200
        assert client.get('/api/calendar').json()['entries']


def test_warning_draft_can_be_approved_and_says_so(ready):
    value = decision()
    value['campaign']['positioning']['en'] = 'A premier getaway'
    def runner(store, opportunity_id, limits, progress):
        return run_opportunity(store, opportunity_id, limits, model(value), progress)
    with TestClient(create_app(str(ready.path), opportunity_runner=runner)) as client:
        job = run_and_wait(client, {'opportunity_id': 'qassim'})
        assert 'warning' in job['message']
        draft = client.get('/api/workspace').json()['campaigns'][0]
        assert draft['validation']['state'] == 'WARNINGS' and draft['status'] == 'PENDING_APPROVAL'
        assert client.post(f"/api/campaigns/{draft['id']}/review", headers=HEADERS, json={'decision': 'APPROVED', 'revision': 0, 'launch_date': '2026-11-10', 'confirmed': True}).status_code == 200


def test_malformed_output_saves_no_draft_but_keeps_the_text(ready):
    with open_store(ready) as store:
        result = run_opportunity(store, 'qassim', Limits(), model('not json'))
        assert result['campaign_id'] is None and result['rejected_output'] == 'not json' and result['errors']


def test_recover_rejected_saves_stored_output_without_a_model_call(ready):
    with open_store(ready) as store:
        db = store.connection
        run_opportunity(store, 'qassim', Limits(), SimpleNamespace(responses=SimpleNamespace(create=lambda **_: (_ for _ in ()).throw(ValueError('x')))))
        output = decision()
        output['campaign']['social_posts'][1]['post_id'] = output['campaign']['social_posts'][0]['post_id']
        output['campaign']['publishing_schedule'][1]['post_id'] = output['campaign']['social_posts'][0]['post_id']
        with db:
            db.execute("UPDATE agent_discovery_cycles SET result_json=?", (json.dumps({'opportunity_id': 'qassim', 'rejected_output': json.dumps(output)}),))
        report = recover_rejected(store)
        assert report[0]['saved'] and recover_rejected(store) == []
        campaign = OpportunityStore(db).campaigns()[0]
        found = review_validation(campaign['campaign'], campaign['evidence'])
        assert found['blocking'] == [] and any('renumbered' in w for w in found['warnings'])
