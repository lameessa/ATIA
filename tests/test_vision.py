"""Offline tests use explicit test doubles; never fabricate live analysis results."""
from io import BytesIO
import json
from unittest.mock import Mock
import pytest

Image = pytest.importorskip('PIL.Image')
from atia.collectors.flickr import FlickrError
from atia.models import normalize
from atia.storage.sqlite import PhotoStore
from atia.vision.images import FlickrImageFetcher, ImageAsset, ImageUnavailable, safe_flickr_url
from atia.vision.model import VisionError
from atia.vision.pipeline import analyze_batch
from atia.vision.prompts import PROMPTS, PROMPT_VERSION
from atia.vision.storage import AnalysisStore

URL = 'https://live.staticflickr.com/1/test.jpg'


def test_allowed_hosts():
    assert safe_flickr_url(URL)
    for url in ('http://live.staticflickr.com/a', 'https://evil.example/a',
                'https://staticflickr.com.evil.example/a', 'https://user:pass@live.staticflickr.com/a',
                'https://live.staticflickr.com:bad/a'):
        assert not safe_flickr_url(url)


def image_bytes():
    output = BytesIO()
    Image.new('RGB', (300, 240), color='blue').save(output, format='JPEG')
    return output.getvalue()


def make_fetcher(tmp_path, body=None, status=200, content_type='image/jpeg'):
    client = Mock()
    client.call.return_value = {'sizes': {'size': [{'source': URL, 'width': 640, 'height': 480, 'media': 'photo'}]}}
    response = Mock(status_code=status, headers={'Content-Type': content_type})
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = iter([image_bytes() if body is None else body])
    session = Mock()
    session.get.return_value = response
    return FlickrImageFetcher(client, tmp_path, session=session, pause=lambda _: None)


def test_valid_image_download_and_hash(tmp_path):
    asset = make_fetcher(tmp_path).fetch({'photo_id': '1'})
    assert asset.image.mode == 'RGB'
    assert (asset.width, asset.height) == (300, 240)
    assert len(asset.sha256) == 64
    from pathlib import Path
    assert Path(asset.path).exists()
    asset.image.close()


@pytest.mark.parametrize('body,status,content_type', [
    (b'broken', 200, 'image/jpeg'), (b'html', 200, 'text/html'),
    (b'', 404, 'image/jpeg'), (b'', 403, 'image/jpeg')])
def test_broken_private_and_inaccessible_images(tmp_path, body, status, content_type):
    with pytest.raises(ImageUnavailable):
        make_fetcher(tmp_path, body, status, content_type).fetch({'photo_id': '1'})


def test_metadata_unavailable_does_not_imply_deletion(tmp_path):
    fetcher = make_fetcher(tmp_path)
    fetcher.client.call.side_effect = FlickrError('API error', code='1')
    with pytest.raises(ImageUnavailable, match='unknown'):
        fetcher.fetch({'photo_id': '1'})


def test_download_size_limit(tmp_path):
    fetcher = make_fetcher(tmp_path)
    fetcher.max_bytes = 2
    with pytest.raises(ImageUnavailable, match='size limit'):
        fetcher.fetch({'photo_id': '1'})


def test_redirect_host_is_revalidated(tmp_path):
    fetcher = make_fetcher(tmp_path)
    response = fetcher.session.get.return_value
    response.status_code = 302
    response.headers = {'Location': 'https://example.com/image.jpg'}
    with pytest.raises(ImageUnavailable, match='unsupported'):
        fetcher.fetch({'photo_id': '1'})
    assert fetcher.session.get.call_count == 1


def mock_model():
    model = Mock(model_name='test-model', pretrained='test-checkpoint', prompt_version=PROMPT_VERSION,
                 prompts=PROMPTS, library_version='test', device='cpu')
    model.score.return_value = {key: index / 10 for index, key in enumerate(PROMPTS)}
    return model


def asset():
    return ImageAsset(Image.new('RGB', (240, 240)), URL, '0'*64, 'test-image', 240, 240)


def test_batch_continues_and_preserves_photos_and_scores():
    with PhotoStore(':memory:') as store:
        for i in range(1, 5):
            store.save(normalize({'id': str(i)}, 'flickr_live'))
        before = [dict(row) for row in store.connection.execute('SELECT * FROM photos')]
        model, fetcher = mock_model(), Mock()
        fetcher.fetch.side_effect = [ImageUnavailable('Unavailable; cause unknown'), asset(), asset()]
        result = analyze_batch(store, fetcher, lambda: model, limit=2, max_candidates=4)
        assert result['complete'] and result['analyzed'] == 2 and result['unavailable'] == 1
        assert store.connection.execute('SELECT COUNT(*) FROM visual_analyses').fetchone()[0] == 2
        row = dict(store.connection.execute('SELECT * FROM visual_analyses LIMIT 1').fetchone())
        assert row['score_type'] == 'cosine_similarity'
        assert json.loads(row['scores']) == model.score.return_value
        assert json.loads(row['top_categories'])[0]['category'] == 'other'
        assert before == [dict(row) for row in store.connection.execute('SELECT * FROM photos')]
        candidates = AnalysisStore(store).candidates(model, 10)
        assert len(candidates) == 2


def test_inference_error_and_shortfall():
    with PhotoStore(':memory:') as store:
        store.save(normalize({'id': '1'}, 'afaq_historical'))
        model, fetcher = mock_model(), Mock()
        model.score.side_effect = VisionError('Inference failed')
        fetcher.fetch.return_value = asset()
        result = analyze_batch(store, fetcher, lambda: model, limit=1)
        assert result['inference_errors'] == 1 and result['shortfall'] == 1
        assert not result['complete']
        assert store.connection.execute('SELECT COUNT(*) FROM visual_analyses').fetchone()[0] == 0


def test_invalid_scores_not_persisted():
    with PhotoStore(':memory:') as store:
        store.save(normalize({'id': '1'}, 'flickr_live'))
        model, fetcher = mock_model(), Mock()
        model.score.return_value = {key: float('nan') for key in PROMPTS}
        fetcher.fetch.return_value = asset()
        result = analyze_batch(store, fetcher, lambda: model, limit=1)
        assert result['inference_errors'] == 1
        assert store.connection.execute('SELECT COUNT(*) FROM visual_analyses').fetchone()[0] == 0


def test_missing_size_metadata_is_unavailable(tmp_path):
    fetcher = make_fetcher(tmp_path)
    fetcher.client.call.return_value = {'sizes': None}
    with pytest.raises(ImageUnavailable, match='No accessible'):
        fetcher.fetch({'photo_id': '1'})
