"""
The map report for one session: saved results + live lookups -> PDF.

Returns the .docx instead where LibreOffice is not installed (see
render.find_soffice for where it is looked up).
"""
import importlib.metadata
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

import ee
from flask import current_app
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping

from application.logic.geos import aoi as aoi_logic
from application.logic.geos import regency as regency_logic
from application.logic.luma import export_job as export_job_logic
from application.logic.luma import lulc_classes, luma as luma_logic, separability
from application.logic.luma.composite import cloud_property, get_optical_collection, is_sentinel2
from application.logic.user import session as session_logic
from application.models.user import Project
from application.utils.common import AppMessageException, ErrorCodeEnum
from luma_ge.data_acquisition import Reflectance_Data

from . import builder, store
from .render import docx_to_pdf, find_soffice

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), 'templates', 'Luma_Report_Template.docx')
PDF_MIME = 'application/pdf'
DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

# Descriptive values the app does not record; the client may send them with the request.
INPUT_KEYS = ('aoi_method', 'aoi_file_name', 'aoi_display_name',
              'sample_source', 'sample_file_name', 'scheme_file_name')
INPUT_CHOICES = {'aoi_method': ('upload', 'draw'), 'sample_source': ('upload', 'onscreen', 'default')}


def scene_list(luma, region):
    """Scenes behind the composite: [{id, t (ms), cloud, tile | path + row}]."""
    sensor = luma['sensor']
    collection, _meta = get_optical_collection(Reflectance_Data(), region, luma['start_date'], luma['end_date'],
                                               sensor, luma['cloud_cover'])
    cloud_prop = cloud_property(sensor)
    sentinel2 = is_sentinel2(sensor)

    def describe(img):
        img = ee.Image(img)
        props = {'id': img.get('system:index'), 't': img.get('system:time_start'), 'cloud': img.get(cloud_prop)}
        if sentinel2:
            props['tile'] = img.get('MGRS_TILE')
        else:
            props['path'] = img.get('WRS_PATH')
            props['row'] = img.get('WRS_ROW')
        return ee.Feature(None, props)

    features = ee.FeatureCollection(collection.map(describe)).getInfo().get('features', [])
    return [f.get('properties', {}) for f in features]


def _separability(session_id):
    """Runs in a worker thread, so it loads its own objects. None when it cannot be computed."""
    try:
        known_session = session_logic.get_session(session_id, validate=True)
        luma = luma_logic.get(known_session, validate=True)
        _known_aoi, aoi = aoi_logic.get_ee_aoi(session_id)
        return separability.analyze_detailed(known_session, aoi, luma)
    except Exception as e:
        current_app.logger.error('report: separability failed: {}'.format(e))
        return None


def _clean_inputs(inputs):
    cleaned = {}
    for key in INPUT_KEYS:
        value = (inputs or {}).get(key) if isinstance(inputs, dict) else None
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()[:120]
        if key in INPUT_CHOICES and value not in INPUT_CHOICES[key]:
            continue
        cleaned[key] = value
    return cleaned


def _ge_version():
    try:
        return 'luma-ge v{}'.format(importlib.metadata.version('luma_ge'))
    except importlib.metadata.PackageNotFoundError:
        return None


def _meta(known_session, account, known_aoi, generation, thematic, inputs):
    meta = _clean_inputs(inputs)

    regency = regency_logic.find_regency(known_aoi.regency_code) if known_aoi.regency_code else None
    if regency:
        meta['aoi_method'] = 'admin'
        meta['aoi_admin_name'] = regency['label']
        meta.setdefault('aoi_display_name', ', '.join(p for p in (regency['label'], regency.get('province')) if p))

    project = Project.query.filter_by(session_id=known_session.id, account_id=account.id).first()
    meta.update({
        'scheme': 'default' if lulc_classes.is_default_scheme(generation['classes']) else 'custom',
        'validation_file_name': (thematic or {}).get('file_name'),
        'account': {'fullname': account.fullname, 'organization_name': account.organization_name,
                    'email': account.email},
        'project': {'id': project.id, 'name': project.name} if project else None,
        'luma_version': os.environ.get('LUMA_VERSION'),
        'ge_version': _ge_version(),
    })
    return meta


def build_report(known_session, account, inputs=None):
    """Returns (file bytes, mimetype, download name) for the session's current map."""
    session_id = known_session.id
    row = store.get(session_id)
    job = export_job_logic.get_export_job(session_id)
    if not row or not row.generation or not job or not job.ee_image_serialized:
        raise AppMessageException('no report data found, please run lulc-map first',
                                  error=ErrorCodeEnum.ERR_VALIDATION)

    known_aoi, aoi = aoi_logic.get_ee_aoi(session_id)
    generation, thematic = row.generation, row.thematic

    results = dict(generation)
    results.update({
        'session_id': session_id,
        'aoi': {
            'area_size': known_aoi.area_size,
            'regency_code': known_aoi.regency_code,
            'geojson': json.loads(json.dumps(mapping(to_shape(known_aoi.geom)))),
        },
        'classified_serialized': job.ee_image_serialized,
        'thematic': thematic,
    })

    # the scene list and separability run beside the figure renders, not after them
    app = current_app._get_current_object()

    def in_app(fn, *args):
        with app.app_context():
            return fn(*args)

    with ThreadPoolExecutor(max_workers=2) as pool:
        scenes = pool.submit(in_app, scene_list, generation['luma'], aoi)
        detail = pool.submit(in_app, _separability, session_id)
        figures, _seconds = builder.build_figures(results)
        results['scenes'] = scenes.result()
        detail = detail.result()
    results['separability'] = detail['summary'] if detail else None
    results['separability_pixel_counts'] = detail['pixel_counts'] if detail else {}
    results['separability_pairs'] = detail['pairs'] if detail else []

    meta = _meta(known_session, account, known_aoi, generation, thematic, inputs)
    luma = generation['luma']
    name = 'Laporan_Luma_{}_{}_{}'.format(luma['sensor'], luma['start_date'], luma['end_date'])

    with tempfile.TemporaryDirectory() as tmp:
        docx_path = os.path.join(tmp, name + '.docx')
        builder.build_docx(results, meta, TEMPLATE_PATH, docx_path, figures=figures)
        soffice = find_soffice()
        if soffice:
            with open(docx_to_pdf(docx_path, tmp, soffice), 'rb') as f:
                return f.read(), PDF_MIME, name + '.pdf'
        current_app.logger.warning('report: LibreOffice (soffice) not found, returning the .docx')
        with open(docx_path, 'rb') as f:
            return f.read(), DOCX_MIME, name + '.docx'
