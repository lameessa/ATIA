import time
import uuid
from atia.vision.images import ImageUnavailable
from atia.vision.model import VisionError
from atia.vision.storage import AnalysisStore


def analyze_batch(store, fetcher, analyzer_factory, limit=10, max_candidates=100,
                  source=None, progress=None):
    if limit < 1 or max_candidates < limit:
        raise ValueError('limit must be positive and max_candidates must be at least limit')
    start = time.monotonic()
    emit = progress or (lambda message: None)
    run_id = str(uuid.uuid4())
    emit('Loading pretrained OpenCLIP model and tourism prompts (first run downloads weights)...')
    model = analyzer_factory()
    model_loaded = time.monotonic()
    analyses = AnalysisStore(store)
    report = {'run_id': run_id, 'model': model.model_name, 'pretrained': model.pretrained,
              'device': model.device, 'prompt_version': model.prompt_version,
              'score_type': 'cosine_similarity', 'requested': limit, 'analyzed': 0,
              'attempted': 0, 'unavailable': 0, 'inference_errors': 0,
              'results': [], 'errors': [], 'model_load_seconds': round(model_loaded-start, 2)}
    seen = set()
    for record in analyses.candidates(model, max_candidates, source):
        if record['photo_id'] in seen:
            continue
        seen.add(record['photo_id'])
        report['attempted'] += 1
        emit(f"[{report['analyzed']}/{limit}] Retrieving {record['source']} photo {record['photo_id']}")
        try:
            asset = fetcher.fetch(record)
        except ImageUnavailable as exc:
            report['unavailable'] += 1
            message = str(exc)
            analyses.attempt(run_id, record, 'unavailable', message)
            report['errors'].append({'photo_id': record['photo_id'], 'source': record['source'], 'status': 'unavailable', 'message': message})
            emit(f"Photo {record['photo_id']} unavailable; continuing (cause not inferred).")
            continue
        try:
            emit(f"[{report['analyzed']}/{limit}] Analyzing {record['photo_id']} on {model.device}")
            scores = model.score(asset.image)
            top = analyses.save(record, model, asset, scores, run_id)
        except (VisionError, ValueError) as exc:
            report['inference_errors'] += 1
            analyses.attempt(run_id, record, 'inference_error', str(exc))
            report['errors'].append({'photo_id': record['photo_id'], 'source': record['source'], 'status': 'inference_error', 'message': str(exc)})
            continue
        finally:
            asset.image.close()
        analyses.attempt(run_id, record, 'success')
        report['analyzed'] += 1
        report['results'].append({'source': record['source'], 'photo_id': record['photo_id'],
                                  'region': record.get('region'), 'top_categories': top})
        emit(f"[{report['analyzed']}/{limit}] Saved {record['photo_id']}: {top[0]['category']} ({top[0]['similarity']:.4f})")
        if report['analyzed'] >= limit:
            break
    report['complete'] = report['analyzed'] == limit
    report['shortfall'] = limit - report['analyzed']
    report['elapsed_seconds'] = round(time.monotonic()-start, 2)
    return report
