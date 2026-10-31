import json
from unittest.mock import Mock
import pytest
pytest.importorskip('PIL')
from atia.models import normalize
from atia.storage.sqlite import PhotoStore
from atia.vision.dimensions import DIMENSION_PROMPTS, Thresholds, interpret
from atia.vision.dimensional_pipeline import analyze_dimensions
from atia.vision.dimensional_storage import DimensionStore
from test_vision import asset


def scores():
    return {dimension: {key: 0.1 for key in labels} for dimension, labels in DIMENSION_PROMPTS.items()}


def test_environment_keeps_strongest_but_marks_weak_or_tied_uncertain():
    values = scores()['environment']
    values['urban'] = 0.2
    result = interpret('environment', values, Thresholds())
    assert result['strongest_match'] == 'urban' and result['label'] is None
    values['urban'] = 0.4
    values['rural'] = 0.39
    assert interpret('environment', values, Thresholds())['uncertain']
    values['rural'] = 0.2
    assert interpret('environment', values, Thresholds())['label'] == 'urban'


def test_elements_are_multi_label_and_no_match_is_not_absence():
    values = scores()['elements']
    values.update(trees=0.4, vegetation=0.35, roads=0.3)
    result = interpret('elements', values, Thresholds())
    assert set(result['possible_matches']) == {'trees', 'vegetation', 'roads'}
    assert result['per_label']['people']['status'] == 'uncertain'


def test_lighting_weather_and_conflicting_lighting():
    values = scores()['conditions']
    values.update(daytime=0.4, cloudy=0.35)
    result = interpret('conditions', values, Thresholds())
    assert result['lighting']['label'] == 'daytime'
    assert result['weather_matches'] == ['cloudy']
    values['nighttime'] = 0.39
    assert interpret('conditions', values, Thresholds())['lighting']['uncertain']


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -0.1, 1.1, True, '0.3'])
def test_invalid_thresholds(value):
    with pytest.raises(ValueError):
        Thresholds(element_min=value)


def test_batching_cache_reinterpretation_and_unchanged_metadata():
    with PhotoStore(':memory:') as store:
        for photo_id in range(10):
            store.save(normalize({'id': str(photo_id), 'datetaken': '2020-01-02 03:04:05'}, 'flickr_live'))
        before = [dict(row) for row in store.connection.execute('SELECT * FROM photos')]
        fetcher = Mock()
        fetcher.fetch.side_effect = lambda record: asset()
        model = Mock(library_version='test', device='cpu')
        batch_lengths = []
        def infer(images):
            batch_lengths.append(len(images))
            return [scores() for _ in images]
        model.score_batch.side_effect = infer
        result = analyze_dimensions(store, fetcher, lambda: model, batch_size=4)
        assert result['complete'] and result['analyzed'] == 10
        assert batch_lengths == [4, 4, 2]
        assert store.connection.execute('SELECT COUNT(*) FROM visual_dimension_analyses').fetchone()[0] == 30
        assert before == [dict(row) for row in store.connection.execute('SELECT * FROM photos')]
        fail = Mock(side_effect=AssertionError('Must not load model'))
        fetcher.fetch.side_effect = AssertionError('Must not retrieve cached image')
        cached = analyze_dimensions(store, fetcher, fail)
        assert cached['cached'] == 10 and cached['analyzed'] == 0 and cached['image_batches'] == 0
        changed = analyze_dimensions(store, fetcher, fail, thresholds=Thresholds(element_min=0.05))
        assert changed['reinterpreted'] == 10 and changed['image_batches'] == 0
        assert len(changed['results'][0]['dimensions']['elements']['possible_matches']) == 10
        assert store.connection.execute('SELECT COUNT(*) FROM visual_dimension_analyses').fetchone()[0] == 60
        assert before == [dict(row) for row in store.connection.execute('SELECT * FROM photos')]
        fail.assert_not_called()


def test_atomic_dimension_validation():
    with PhotoStore(':memory:') as store:
        record = normalize({'id': '1'}, 'flickr_live')
        store.save(record)
        dimensions = DimensionStore(store)
        malformed = scores()
        malformed['conditions']['nighttime'] = float('nan')
        with pytest.raises(ValueError):
            dimensions.save(record.to_dict(), {}, malformed, Thresholds(), 'test')
        assert store.connection.execute('SELECT COUNT(*) FROM visual_dimension_analyses').fetchone()[0] == 0
