# application/logic/luma/predictor_optimizer.py
"""
Predictor optimizer: which of the available predictors help separate the
session's training classes (workflow chart: "Optimize predictor selection").

GET /luma/predictor/optimize streams its progress as NDJSON lines shaped like
/luma/lulc-map ({process, data, w, a, next}) and ends with the recommendation,
which is also stored on the session (luma_general.predictor_recommendation).

The app runs under gevent (run.py), where a CPU-bound fit would freeze every
other request of the worker. The run therefore happens in its own thread (a
greenlet under gevent) and hands control back after every model fit.
"""
import json
import queue
import threading
import time
from types import SimpleNamespace

import ee
import pandas as pd

from flask import current_app

from application import db
from application.logic.geos.aoi import converter
from application.logic.luma import predictor as predictor_logic
from application.logic.luma import predictor_rules as rules
from application.logic.luma.separability import training_gdf
from application.models.luma import TrainingData
from application.utils.common import AppMessageException, ErrorCodeEnum, get_date

from luma_ge.predictor import RFE_CV

CLASS_PROPERTY = 'class_id'
MAX_SAMPLES = 5000        # same cap as the engine's RFE_CV default
PAGE_SIZE = 4000          # Earth Engine computeFeatures page size
HEARTBEAT_SECONDS = 10    # keeps proxies from closing a quiet connection
# Pause after each model fit. Under gevent it has to be longer than zero:
# sleep(0) only yields to greenlets that are already runnable, so requests
# waiting on a socket or a timer would still starve for the whole run.
FIT_PAUSE_SECONDS = 0.001

PROCESSES = [
    { 'name': 'preparation', 'w': 0.5 },
    { 'name': 'compute predictors', 'w': 3.0 },
    { 'name': 'sample training data', 'w': 6.0 },
    { 'name': 'select predictors', 'w': 10.0 },
    { 'name': 'end', 'w': 0.5 },
]
TOTAL_W = sum(p['w'] for p in PROCESSES)
_WEIGHTS = {p['name']: p['w'] for p in PROCESSES}
_NEXT = {p['name']: n['name'] for p, n in zip(PROCESSES, PROCESSES[1:])}


class _Cancelled(Exception):
    """Raised inside the fit when the client has gone away."""


def _date(value):
    return value.strftime('%Y-%m-%d') if value else None


def _line(process, data=None, weight=None):
    """One NDJSON line. 'a' is the progress this line adds, out of 'w'."""
    return json.dumps({
        'process': process,
        'data': data or {},
        'w': TOTAL_W,
        'a': _WEIGHTS.get(process, 0) if weight is None else weight,
        'next': _NEXT.get(process, ''),
    }) + '\n'


def current_inputs(known_session, luma):
    """What a recommendation depends on, as it is now (see predictor_rules.recommendation_inputs)."""
    query = (
        db.select(
            TrainingData.class_id,
            db.func.count().label('count'),
            db.func.max(TrainingData.modified_date).label('modified'),
        )
        .where(TrainingData.session_id == known_session.id)
        .group_by(TrainingData.class_id)
    )
    rows = db.session.execute(query).all()
    latest = max((row.modified for row in rows if row.modified is not None), default=None)

    return rules.recommendation_inputs(
        sensor=luma.landsat_version,
        start_date=_date(luma.start_date),
        end_date=_date(luma.end_date),
        cloud_cover=luma.cloud_cover,
        spatial_resolution=luma.spatial_resolution,
        training_counts={row.class_id: row.count for row in rows},
        training_modified=latest.isoformat() if latest else None,
    )


def saved_recommendation(known_session, luma):
    """The session's last optimizer result with a 'stale' flag, or None."""
    if not luma.predictor_recommendation:
        return None
    return rules.public_recommendation(luma.predictor_recommendation, current_inputs(known_session, luma))


def prepare(known_session, luma, candidate_ids):
    """
    Everything a run needs from the request and the database, checked before
    the stream starts so that problems come back as a normal error response.

    candidate_ids: predictors to choose among; empty means every predictor
    available for the session.
    """
    if candidate_ids:
        ids = predictor_logic.validated_ids(luma, candidate_ids, allow_conflicts=True)
    else:
        ids = predictor_logic.available_ids(luma)
    if not ids:
        raise AppMessageException('no predictor is available for this session', error=ErrorCodeEnum.ERR_VALIDATION)

    train_gdf = training_gdf(known_session.id)
    if train_gdf.empty or train_gdf[CLASS_PROPERTY].nunique() < 2:
        raise AppMessageException(
            'training data (step-3) with at least two classes is required',
            error=ErrorCodeEnum.ERR_VALIDATION,
        )

    return {
        'ids': ids,
        'train_gdf': train_gdf,
        'inputs': current_inputs(known_session, luma),
        # A plain copy of the session values the worker thread reads, so the
        # thread never touches the request's database session.
        'session': SimpleNamespace(
            landsat_version=luma.landsat_version,
            start_date=luma.start_date,
            end_date=luma.end_date,
            cloud_cover=luma.cloud_cover,
            spatial_resolution=luma.spatial_resolution,
            use_predictor=False,
            predictor_config=None,
        ),
    }


def stream(job, aoi, luma):
    """Generator of NDJSON lines for a prepared run; stores the recommendation on `luma` at the end."""
    yield _line('preparation', { 'processes': PROCESSES, 'candidates': job['ids'] })

    events = queue.Queue()
    cancelled = threading.Event()
    app = current_app._get_current_object()
    threading.Thread(target=_run, args=(app, job, aoi, events, cancelled), daemon=True).start()

    select_weight = _WEIGHTS['select predictors']
    select_emitted = 0.0
    outcome = None
    try:
        while outcome is None:
            try:
                kind, payload = events.get(timeout=HEARTBEAT_SECONDS)
            except queue.Empty:
                yield _line('heartbeat', weight=0)
                continue

            if kind == 'step':
                yield _line(payload['process'], payload['data'])
            elif kind == 'fit':
                completed, total = payload
                target = select_weight * min(1.0, completed / total) if total else 0.0
                step = max(0.0, target - select_emitted)
                select_emitted += step
                yield _line('select predictors', { 'completed': completed, 'total': total }, weight=step)
            elif kind == 'error':
                yield _line('error', { 'message': payload }, weight=0)
                return
            else:
                outcome = payload
    finally:
        # Reached on normal end too. If the client disconnected mid-run, this
        # stops the fit at its next step instead of letting it run to the end.
        cancelled.set()

    recommendation = rules.build_recommendation(
        outcome['selection'], outcome['ranking'], outcome['support'], outcome['importances']
    )
    recommendation.update({
        'candidates': [item['id'] for item in outcome['selection']],
        'skipped': outcome['skipped'],
        'samples': outcome['samples'],
        'created': get_date().isoformat(),
        'inputs': job['inputs'],
    })

    try:
        luma.predictor_recommendation = recommendation
        db.session.add(luma)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('predictor optimizer: could not save the recommendation: {}'.format(e))

    # the last line also carries whatever weight the fit lines did not cover
    yield _line(
        'end',
        { 'recommendation': rules.public_recommendation(recommendation, job['inputs']) },
        weight=_WEIGHTS['end'] + (select_weight - select_emitted),
    )


def _run(app, job, aoi, events, cancelled):
    """
    Worker thread: stack the candidates, sample them at the training data,
    run the engine's RFE_CV. Reports through `events`:
        ('step', {'process', 'data'})   a process finished
        ('fit', (completed, total))     one model fit of the selection finished
        ('done', {...})                 the result
        ('error', message)
    """
    with app.app_context():
        try:
            session = job['session']

            stack, selection, skipped = predictor_logic.session_stack(session, aoi, job['ids'])
            events.put(('step', {
                'process': 'compute predictors',
                'data': { 'candidates': [item['id'] for item in selection], 'skipped': skipped },
            }))

            frame = _sample(stack, job['train_gdf'], session.spatial_resolution or 30)
            if frame.empty or CLASS_PROPERTY not in frame.columns:
                raise AppMessageException('no training sample falls on valid imagery')

            predictor_bands = [item['band'] for item in selection]
            features = [
                column for column in frame.columns
                if column != CLASS_PROPERTY and column not in predictor_bands
            ] + [band for band in predictor_bands if band in frame.columns]
            samples = {
                'total': int(len(frame)),
                'per_class': {
                    str(int(class_id)): int(count)
                    for class_id, count in frame[CLASS_PROPERTY].value_counts().sort_index().items()
                },
            }
            events.put(('step', {
                'process': 'sample training data',
                'data': { 'samples': samples['total'], 'features': len(features) },
            }))

            def on_fit(completed, total, phase):
                if cancelled.is_set():
                    raise _Cancelled()
                events.put(('fit', (completed, total)))
                # Under gevent this lets the other requests of the worker run
                # between two model fits; with real threads it costs 1 ms.
                time.sleep(FIT_PAUSE_SECONDS)

            selector = RFE_CV(
                training_data=frame,
                class_property=CLASS_PROPERTY,
                features=features,
                progress_callback=on_fit,
                verbose=False,
            )
            selector.fit()

            events.put(('done', {
                'selection': selection,
                'skipped': skipped,
                'ranking': selector.get_ranking(),
                'support': selector.get_support(),
                'importances': selector.feature_importances_,
                'samples': samples,
            }))
        except _Cancelled:
            app.logger.info('predictor optimizer: cancelled, the client disconnected')
        except (AppMessageException, ValueError) as e:
            # ValueError: the engine's own checks (e.g. a class with fewer than 2 samples)
            events.put(('error', str(e)))
        except Exception as e:
            app.logger.exception('predictor optimizer failed')
            events.put(('error', 'predictor optimization failed: {}'.format(e)))


def _sample(stack, train_gdf, scale):
    """
    Stack values at the training data -> DataFrame, one row per sampled pixel.
    Capped per class on Earth Engine and read page by page, so it is not bound
    by the 5000-element limit of a plain getInfo().
    """
    class_ids = sorted(int(class_id) for class_id in train_gdf[CLASS_PROPERTY].unique())
    samples = stack.sampleRegions(
        collection=converter.convert_roi_gdf(train_gdf),
        properties=[CLASS_PROPERTY],
        scale=scale,
        geometries=False,
        tileScale=16,
    )
    per_class = max(2, MAX_SAMPLES // len(class_ids))
    capped = ee.FeatureCollection([
        samples.filter(ee.Filter.eq(CLASS_PROPERTY, class_id)).limit(per_class)
        for class_id in class_ids
    ]).flatten()

    rows = []
    page_token = None
    while True:
        params = { 'expression': capped, 'pageSize': PAGE_SIZE }
        if page_token:
            params['pageToken'] = page_token
        response = ee.data.computeFeatures(params) or {}
        rows.extend(feature.get('properties') or {} for feature in response.get('features') or [])
        page_token = response.get('nextPageToken')
        if not page_token:
            break

    return pd.DataFrame(rows)
