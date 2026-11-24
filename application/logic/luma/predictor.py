import ee

from concurrent.futures import ThreadPoolExecutor
from flask import current_app

from application import db
from application.feature_flags import mosaic_parallel_workers
from application.logic.luma import predictor_rules as rules
from application.logic.luma import predictor_vis as vis
from application.logic.luma.composite import build_composite

from application.utils.common import AppMessageException
from application.utils.common import ErrorCodeEnum

from application.logic.luma import engine_compat  # noqa: F401  (must come before luma_ge.predictor)
from luma_ge.predictor import PredictorCalculation, predictor_catalog, sensor_detector

SKIPPED_REASON = 'no data for this area and period'


def _date(value):
    return value.strftime('%Y-%m-%d') if value else None


def _session_context(luma):
    """
    Engine catalog plus its availability for the session's sensor and period.
    A lookup in the engine's own table: no Earth Engine request.
    """
    catalog = predictor_catalog.get_all_catalog()
    availability = predictor_catalog.check_availability(
        sensor=luma.landsat_version,
        start_date=_date(luma.start_date),
        end_date=_date(luma.end_date),
    )
    sensor_family = sensor_detector.normalize_sensor_name(luma.landsat_version)
    return catalog, availability, sensor_family


def list_available(luma):
    """Grouped predictors, each flagged available or not, plus the saved selection."""
    catalog, availability, sensor_family = _session_context(luma)
    listing = rules.build_listing(
        catalog,
        availability,
        sensor_code=luma.landsat_version,
        sensor_family=sensor_family,
        selected=rules.selected_ids(luma.predictor_config),
    )
    listing['sensor'] = luma.landsat_version
    listing['start_date'] = _date(luma.start_date)
    listing['end_date'] = _date(luma.end_date)
    return listing


def validated_ids(luma, predictors, allow_conflicts=False):
    """
    Request value -> predictor ids this session can use (AppMessageException otherwise).
    allow_conflicts: accept a pair that cannot be saved together (optimizer candidates).
    """
    catalog, availability, sensor_family = _session_context(luma)
    try:
        ids = rules.normalize_selection(predictors)
        rules.validate_selection(
            ids,
            catalog,
            availability,
            sensor_code=luma.landsat_version,
            sensor_family=sensor_family,
            allow_conflicts=allow_conflicts,
        )
    except ValueError as e:
        raise AppMessageException(str(e), error=ErrorCodeEnum.ERR_VALIDATION)
    return ids


def available_ids(luma):
    """Every predictor the session can use (the optimizer's default candidates)."""
    catalog, availability, sensor_family = _session_context(luma)
    return rules.available_ids(
        catalog,
        availability,
        sensor_code=luma.landsat_version,
        sensor_family=sensor_family,
    )


def set_predictor_config(known_session, luma, predictors):
    ids = validated_ids(luma, predictors)

    luma.use_predictor = len(ids) > 0
    luma.predictor_config = rules.build_engine_config(ids, predictor_catalog.get_all_catalog())

    db.session.add(luma)
    db.session.commit()


def selected_labels(luma):
    """Display names of the saved selection (summaries, export metadata)."""
    return rules.selected_labels(luma.predictor_config, predictor_catalog.get_all_catalog())


def engine_config(luma, predictor_config=None):
    """
    A predictor_config (the saved one by default) plus what the engine reads
    from the session: the sensor, and the period the radar predictors are
    composited over.
    """
    config = dict(luma.predictor_config or {}) if predictor_config is None else dict(predictor_config)
    config['sensor'] = luma.landsat_version
    if luma.start_date and luma.end_date:
        config['start_date'] = _date(luma.start_date)
        config['end_date'] = _date(luma.end_date)
    return config


def compute_stack(luma, composite, aoi, collection=None, ids=None):
    """
    Composite bands plus predictors, as one image.

    ids: predictor ids to stack; None means the session's saved selection.

    Returns the composite unchanged when there is no predictor to add, and
    None when the engine could not compute them (same as the engine's own
    'stacked_predictors').
    """
    if composite is None:
        return None
    if ids is None:
        if not luma.use_predictor or not luma.predictor_config:
            return composite
        config = engine_config(luma)
    else:
        if not ids:
            return composite
        config = engine_config(luma, rules.build_engine_config(ids, predictor_catalog.get_all_catalog()))

    service = PredictorCalculation()
    result = service.compute_predictors(
        composite=composite,
        aoi=aoi,
        predictor_config=config,
        collection=collection,
        sensor=luma.landsat_version,
    )
    for warning in result.get('warnings') or []:
        current_app.logger.warning('predictors: {}'.format(warning))

    parts = result.get('predictors') or {}
    if not result.get('success') or not parts:
        current_app.logger.error('predictors: engine failed: {}'.format(result.get('errors')))
        return None

    # Stack the engine's parts here rather than taking its 'stacked_predictors',
    # so every band keeps the name of its predictor: spyndex leaves a single
    # index named after its first input band (NDVI alone comes back as 'NIR').
    spectral_indices = (config.get('individual_predictors') or {}).get('spectral_indices') or []
    stack = None
    for key, part in parts.items():
        if key == 'spectral' and len(spectral_indices) == 1:
            part = part.rename(spectral_indices)
        stack = part if stack is None else stack.addBands(part)

    for band in _composite_indices(service, composite, config):
        stack = stack.addBands(band)

    return stack


def _composite_indices(service, composite, config):
    """
    Indices that need the thermal band (EBBI). The engine maps spectral
    indices over the optical collection, which has no thermal band, so these
    are computed from the composite, where the backend has added it.
    """
    bands = []
    for name in config.get('composite_indices') or []:
        image = service.spectral_calc.calculate_indices(
            image=composite,
            index_list=[name],
            sensor=config.get('sensor'),
        )
        if image is None:
            current_app.logger.warning('predictors: {} skipped, the composite lacks a band it needs'.format(name))
            continue
        bands.append(image.rename([name]))
    return bands


def stack_selection(luma, composite, aoi, collection, ids):
    """
    The given predictors stacked on a composite.

    -> (stack, selection, skipped)
       selection  predictor_rules.selection_bands() entries present in the stack
       skipped    [{'id', 'label', 'reason'}] the engine could not produce,
                  for example no radar scene in the period
    """
    stack = compute_stack(luma, composite, aoi, collection=collection, ids=ids)
    if stack is None:
        raise AppMessageException('predictors could not be computed, please check the imagery parameters (step-1)')

    present = set(stack.bandNames().getInfo())
    selection, skipped = [], []
    for item in rules.selection_bands(ids, predictor_catalog.get_all_catalog()):
        if item['band'] in present:
            selection.append(item)
        else:
            skipped.append({'id': item['id'], 'label': item['label'], 'reason': SKIPPED_REASON})
    return stack, selection, skipped


def session_stack(luma, aoi, ids):
    """stack_selection() on a composite built from the imagery parameters saved by /image-mosaic."""
    composite, collection = build_composite(
        aoi,
        _date(luma.start_date),
        _date(luma.end_date),
        luma.landsat_version or 'L8_SR',
        luma.cloud_cover if luma.cloud_cover is not None else 30,
        return_collection=True,
        # /image-mosaic already found images for these parameters; counting
        # them again costs several Earth Engine round-trips.
        check_images=False,
    )
    return stack_selection(luma, composite, aoi, collection, ids)


def preview(luma, aoi, ids):
    """
    Tile layers for the given predictors, each with a default colour scheme.
    -> {'layers': [{'id', 'label', 'name', 'url', 'kind', 'min', 'max', 'palette'[, 'classes']}], 'skipped': [...]}
    """
    stack, selection, skipped = session_stack(luma, aoi, ids)
    stats = _stretch_stats(stack, aoi, luma, vis.stretch_bands(selection))

    def render(item):
        style = vis.build_style(item, stats)
        image = stack.select(item['band'])
        if item['id'] == vis.LANDFORM_ID:
            image = image.remap(*vis.landform_remap())
        map_id = image.getMapId(vis.ee_params(style))
        layer = {
            'id': item['id'],
            'label': item['label'],
            'name': 'Predictor - {}'.format(item['label']),
            'url': map_id['tile_fetcher'].url_format,
        }
        layer.update(vis.public_style(style))
        return layer

    layers = []
    workers = max(1, min(mosaic_parallel_workers(), len(selection)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [(item, pool.submit(render, item)) for item in selection]
        for item, future in futures:
            try:
                layers.append(future.result())
            except Exception as e:
                current_app.logger.warning('predictor preview: {} failed: {}'.format(item['id'], e))
                skipped.append({'id': item['id'], 'label': item['label'], 'reason': str(e)})

    return {'layers': layers, 'skipped': skipped}


def _stretch_stats(stack, aoi, luma, bands):
    """
    2nd / 98th percentile of each band over the AOI, in one request. Earth
    Engine coarsens the scale as needed (bestEffort), so this stays cheap on
    large areas. {} when it fails: the layers then use fixed default ranges.
    """
    if not bands:
        return {}
    try:
        stats = stack.select(bands).reduceRegion(
            reducer=ee.Reducer.percentile(vis.PERCENTILES),
            geometry=aoi,
            scale=luma.spatial_resolution or 30,
            bestEffort=True,
            maxPixels=1e6,
            tileScale=4,
        ).getInfo()
        return stats or {}
    except Exception as e:
        current_app.logger.warning('predictor preview: percentile stretch failed, using default ranges: {}'.format(e))
        return {}


def download_url(luma, aoi, session_id, ids):
    """
    GeoTIFF download URL with one band per predictor, named by predictor id.
    'download_url' is '' when Earth Engine refuses (e.g. > 50 MB request),
    like the mosaic download.
    """
    stack, selection, skipped = session_stack(luma, aoi, ids)
    result = {
        'download_url': '',
        'bands': [item['id'] for item in selection],
        'skipped': skipped,
    }
    if not selection:
        return result

    # one data type for every band, as a multi-band GeoTIFF requires
    image = stack.select(
        [item['band'] for item in selection],
        [item['id'] for item in selection],
    ).toFloat()
    try:
        result['download_url'] = image.getDownloadURL({
            "name": 'LULC_{sensor}_{start_date}_{end_date}_{session_id}_PRED'.format(
                sensor=luma.landsat_version,
                start_date=_date(luma.start_date),
                end_date=_date(luma.end_date),
                session_id=session_id,
            ),
            "crs": 'EPSG:4326',
            "scale": luma.spatial_resolution or 30,
            "region": aoi,
            "filePerBand": False,
            "fileFormat": "GEO_TIFF",
            "formatOptions": {"cloudOptimized": True}
        })
    except Exception as e:
        current_app.logger.error('failed to get predictor download url: {}'.format(str(e)))
    return result
