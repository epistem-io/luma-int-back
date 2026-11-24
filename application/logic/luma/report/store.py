"""
Keeps what the map report needs from a run, one row per session
(luma_report_data): the generation snapshot and the latest thematic accuracy
test. Scenes and separability are not stored; the report service looks them up
when the report is built.
"""
import math
from datetime import date, datetime

import numpy as np

from application import db
from application.models.luma import ReportData
from application.utils.common import get_date


def _plain(value):
    """numpy values, datetimes and NaN -> plain JSON values (JSONB accepts nothing else)."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, np.ndarray):
        return _plain(value.tolist())
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        value = float(value)
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def generation_snapshot(luma, classes, train_gdf, lulc_composition, feature_importance, model_quality):
    """What the map was made from and what came out, as plain JSON."""
    points = []
    for row in train_gdf.itertuples():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        point = geom if geom.geom_type == 'Point' else geom.representative_point()
        points.append({'class_id': int(row.class_id), 'lon': float(point.x), 'lat': float(point.y)})

    return _plain({
        'generated_at': get_date().isoformat(),
        'luma': {
            'sensor': luma.landsat_version,
            'start_date': luma.start_date.strftime('%Y-%m-%d'),
            'end_date': luma.end_date.strftime('%Y-%m-%d'),
            'cloud_cover': luma.cloud_cover,
            'spatial_resolution': luma.spatial_resolution,
            'ntrees': luma.ntrees,
            'min_leaf': luma.min_leaf,
            'split_ratio': luma.split_ratio or 0.7,
            'use_predictor': bool(luma.use_predictor),
            'predictor_config': luma.predictor_config,
        },
        'classes': [{'class_id': int(c.class_id), 'class_name': c.class_name, 'class_color': c.class_color}
                    for c in sorted(classes, key=lambda c: c.class_id)],
        'training': {'points': points},
        'lulc_composition': lulc_composition,
        'feature_importance': feature_importance,
        'model_quality': model_quality,
    })


def get(session_id):
    return ReportData.query.filter_by(session_id=session_id).first()


def save_generation(session_id, snapshot):
    """A new map replaces the previous snapshot and invalidates the old accuracy test."""
    row = get(session_id) or ReportData(session_id=session_id)
    row.generation = snapshot
    row.thematic = None
    db.session.add(row)
    db.session.commit()
    return row


def save_thematic(session_id, assessment, file_name=None):
    """Attach a thematic accuracy result to the session's current map; no map on record -> nothing saved."""
    row = get(session_id)
    if not row:
        return None
    row.thematic = _plain(dict(assessment, file_name=file_name))
    db.session.add(row)
    db.session.commit()
    return row


def clear(session_id):
    ReportData.query.filter_by(session_id=session_id).delete()
    db.session.commit()
