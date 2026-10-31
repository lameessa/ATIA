import json
import time
import uuid
from dataclasses import asdict
from atia.vision.dimensions import Thresholds, DIMENSION_PROMPT_VERSION
from atia.vision.dimensional_model import DimensionalAnalyzer
from atia.vision.dimensional_storage import DimensionStore, asset_metadata, cached_metadata
from atia.vision.images import ImageUnavailable
from atia.vision.model import VisionError
from atia.vision.storage import AnalysisStore


def analyze_dimensions(store, fetcher, analyzer_factory=DimensionalAnalyzer, limit=10,
                       max_candidates=100, batch_size=4, thresholds=None, source=None, progress=None):
    if limit < 1 or max_candidates < limit or batch_size < 1:
        raise ValueError('Positive limit/batch-size and max-candidates >= limit required')
    started = time.monotonic()
    emit = progress or (lambda message: None)
    thresholds = thresholds or Thresholds()
    dimension_store = DimensionStore(store)
    attempts = AnalysisStore(store)
    report = {'run_id': str(uuid.uuid4()), 'model': DimensionalAnalyzer.model_name,
              'pretrained': DimensionalAnalyzer.pretrained, 'prompt_version': DIMENSION_PROMPT_VERSION,
              'thresholds': asdict(thresholds), 'threshold_version': thresholds.version,
              'requested': limit, 'analyzed': 0, 'cached': 0, 'reinterpreted': 0,
              'image_batches': 0, 'unavailable': 0, 'inference_errors': 0,
              'results': [], 'errors': [], 'score_type': 'cosine_similarity'}
    model = None
    pending = []
    seen = set()

    def finish(record, interpretations, mode):
        report['results'].append({'source': record['source'], 'photo_id': record['photo_id'],
                                  'region': record['region'], 'mode': mode, 'dimensions': interpretations})
        emit(f"[{len(report['results'])}/{limit}] {record['photo_id']}: {mode}; environment "
             f"{interpretations['environment']['strongest_match']} ({interpretations['environment']['status']})")

    def flush():
        nonlocal model
        if not pending:
            return
        try:
            if model is None:
                emit('Loading cached pretrained model and encoding all dimension prompts once...')
                model = analyzer_factory()
            emit(f'Encoding image batch of {len(pending)}...')
            score_sets = model.score_batch([asset.image for _, asset in pending])
            report['image_batches'] += 1
            if len(score_sets) != len(pending):
                raise VisionError('Unexpected number of batched score sets')
            for (record, asset), scores in zip(pending, score_sets):
                try:
                    interpretations = dimension_store.save(record, asset_metadata(asset, model), scores, thresholds, report['run_id'])
                except ValueError as exc:
                    report['inference_errors'] += 1
                    report['errors'].append({'photo_id': record['photo_id'], 'message': str(exc)})
                    attempts.attempt(report['run_id'], record, 'inference_error', str(exc))
                    continue
                report['analyzed'] += 1
                attempts.attempt(report['run_id'], record, 'dimension_success')
                finish(record, interpretations, 'inferred')
        except VisionError as exc:
            for record, _ in pending:
                report['inference_errors'] += 1
                report['errors'].append({'photo_id': record['photo_id'], 'message': str(exc)})
                attempts.attempt(report['run_id'], record, 'inference_error', str(exc))
        finally:
            for _, asset in pending:
                asset.image.close()
            pending.clear()

    for record in dimension_store.candidates(max_candidates, source):
        if record['photo_id'] in seen:
            continue
        seen.add(record['photo_id'])
        cached = dimension_store.cached(record, thresholds)
        if cached:
            report['cached'] += 1
            finish(record, {dimension: json.loads(row['interpretation']) for dimension, row in cached.items()}, 'cached')
        else:
            cached_scores = dimension_store.cached(record)
            if cached_scores:
                scores = {dimension: json.loads(row['scores']) for dimension, row in cached_scores.items()}
                interpretations = dimension_store.save(record, cached_metadata(cached_scores), scores, thresholds, report['run_id'])
                report['reinterpreted'] += 1
                finish(record, interpretations, 'reinterpreted')
            else:
                emit(f"Retrieving {record['photo_id']} ({len(report['results'])}/{limit} completed)...")
                try:
                    pending.append((record, fetcher.fetch(record)))
                except ImageUnavailable as exc:
                    report['unavailable'] += 1
                    report['errors'].append({'photo_id': record['photo_id'], 'message': str(exc)})
                    attempts.attempt(report['run_id'], record, 'unavailable', str(exc))
                    emit(f"{record['photo_id']}: unavailable; continuing without inferring a cause.")
        if pending and (len(pending) >= batch_size or len(report['results']) + len(pending) >= limit):
            flush()
        if len(report['results']) >= limit:
            break
    flush()
    report['completed'] = len(report['results'])
    report['complete'] = report['completed'] == limit
    report['shortfall'] = limit - report['completed']
    report['elapsed_seconds'] = round(time.monotonic() - started, 2)
    return report
