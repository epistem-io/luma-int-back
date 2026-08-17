# application/logic/geos/regency.py
import ee
import os
import time
import threading
import logging

from application.utils.common import AppMessageException, ErrorCodeEnum
from application.logic.geos.regency_options import build_regency_options

logger = logging.getLogger(__name__)

REGENCY_ASSET_PATH = os.environ.get(
    'REGENCY_ASSET_PATH',
    'projects/ee-rg2icraf/assets/Indonesian_Regency_Area',
)
REGENCY_CODE_PROPERTY = 'KDPKAB'
REGENCY_NAME_PROPERTY = 'WADMKK'
REGENCY_PROVINCE_PROPERTY = 'WADMPR'
REGENCY_TYPE_PROPERTY = 'TIPADM'

# Order must match build_regency_options(): [code, name, province, tipadm]
_LIST_SELECTORS = [
    REGENCY_CODE_PROPERTY,
    REGENCY_NAME_PROPERTY,
    REGENCY_PROVINCE_PROPERTY,
    REGENCY_TYPE_PROPERTY,
]

REGENCY_LIST_CACHE_TTL = int(os.environ.get('REGENCY_LIST_CACHE_TTL', 60 * 60 * 24))  # seconds

_cache_lock = threading.Lock()
_cache = {'options': None, 'expires_at': 0.0}


def _asset():
    return ee.FeatureCollection(REGENCY_ASSET_PATH)


def _fetch_regency_options():
    rows = (
        _asset()
        .reduceColumns(ee.Reducer.toList(len(_LIST_SELECTORS)), _LIST_SELECTORS)
        .get('list')
        .getInfo()
    )
    options = build_regency_options(rows)
    if not options:
        raise AppMessageException('regency list is empty', error=ErrorCodeEnum.ERR_INTERNAL)
    return options


def list_regencies(force_refresh=False):
    """Return cached list of regency option dicts {code, name, type, province, label}."""
    now = time.time()
    with _cache_lock:
        if not force_refresh and _cache['options'] and _cache['expires_at'] > now:
            return _cache['options']

    options = _fetch_regency_options()

    with _cache_lock:
        _cache['options'] = options
        _cache['expires_at'] = time.time() + REGENCY_LIST_CACHE_TTL

    logger.info('regency list refreshed: %d entries', len(options))
    return options


def find_regency(code):
    """Return the option dict for `code`, or None."""
    code = (code or '').strip()
    if not code:
        return None
    for option in list_regencies():
        if option['code'] == code:
            return option
    return None


def get_regency_ee_geometry(code):
    """
    Server-side ee.Geometry for a regency code — a lazy reference to the GEE
    asset, no coordinates transferred. Raises AppMessageException for an
    unknown code (validated against the cached list, no EE round-trip).
    """
    option = find_regency(code)
    if not option:
        raise AppMessageException(
            'regency not found for code: {}'.format(code),
            error=ErrorCodeEnum.ERR_NOT_FOUND,
        )
    return _asset().filter(ee.Filter.eq(REGENCY_CODE_PROPERTY, option['code'])).geometry()


def get_regency_geojson(code):
    """
    Resolve a regency code to its (unioned) polygon and area.

    Geometry and area are computed server-side in a single getInfo() call —
    round-tripping a large coastal MultiPolygon back into EE for area() costs
    tens of seconds.

    Returns:
        (geometry_geojson: dict, area_m2: float, option: dict)
    Raises:
        AppMessageException if the code is unknown or has no geometry.
    """
    option = find_regency(code)
    if not option:
        raise AppMessageException(
            'regency not found for code: {}'.format(code),
            error=ErrorCodeEnum.ERR_NOT_FOUND,
        )

    # A regency may be stored as several features (islands / enclaves);
    # FeatureCollection.geometry() dissolves them into one geometry.
    filtered = _asset().filter(ee.Filter.eq(REGENCY_CODE_PROPERTY, option['code']))
    ee_geometry = filtered.geometry()

    result = ee.Dictionary({
        'geometry': ee_geometry,
        'area': ee_geometry.area(),
    }).getInfo()

    geometry = (result or {}).get('geometry')
    area_m2 = (result or {}).get('area') or 0

    if not geometry or not geometry.get('coordinates'):
        raise AppMessageException(
            'regency geometry is empty for code: {}'.format(code),
            error=ErrorCodeEnum.ERR_NOT_FOUND,
        )

    return geometry, area_m2, option
