# application/logic/luma/predictor_rules.py
"""
Rules for the predictor step, free of Flask and Earth Engine imports so they
can be unit-tested by file path (tests/test_predictor_rules.py).

The engine owns the list of predictors (luma_ge.predictor.predictor_catalog).
This module turns that catalog into what the API exposes, and a saved
selection back into the predictor_config the engine computes from.

Every function takes the engine catalog as an argument:
    catalog      = predictor_catalog.PREDICTORS          (name -> metadata)
    availability = predictor_catalog.check_availability  (name -> info)
"""

GROUP_ORDER = ['vegetation', 'waterHumidity', 'landBuiltUp', 'terrain', 'radar', 'distance', 'other']

# Engine category (Indonesian display text) -> key the frontend translates.
CATEGORY_GROUPS = {
    'Vegetasi': 'vegetation',
    'Air & Kelembaban': 'waterHumidity',
    'Tanah dan Lahan Terbangun': 'landBuiltUp',
    'Topografi': 'terrain',
    'Polarisasi Radar': 'radar',
    'Jarak & Aksesibilitas': 'distance',
}
TYPE_GROUPS = {'terrain': 'terrain', 'radar': 'radar', 'distance': 'distance'}

# Engine catalog name -> (API id, engine config key, band in the stacked image).
RADAR = {
    'VV': ('VV', 'sentinel1', 'S1_VV'),
    'VH': ('VH', 'sentinel1', 'S1_VH'),
    'VV-VH Ratio': ('VV_VH', 'sentinel1', 'S1_VV_VH'),
    'HH': ('HH', 'palsar', 'PALSAR_HH'),
    'HV': ('HV', 'palsar', 'PALSAR_HV'),
    'HV-HH Ratio': ('HV_HH', 'palsar', 'PALSAR_HH_HV'),
}

# No longer in the engine catalog, but the engine still computes them (spyndex
# knows them). Accepted on save so older checkpoints keep working; never listed.
# name -> group
LEGACY_SPECTRAL = {
    'OSAVI': 'vegetation',
    'ARVI': 'vegetation',
    'GBNDVI': 'vegetation',
    'AWEInsh': 'waterHumidity',
}

CONFLICTING_PREDICTORS = [('EVI', 'SAVI')]

# Band symbols (spyndex notation) the composite of each sensor carries.
# 'T' is the thermal band the backend adds from the TOA collection.
THERMAL_BAND = 'T'
_LANDSAT_MSS = frozenset({'G', 'R'})  # NIR1 / NIR2 are not read as 'N' by the engine
_LANDSAT_SR = frozenset({'B', 'G', 'R', 'N', 'S1', 'S2', THERMAL_BAND})
SENSOR_BANDS = {
    'L1_RAW': _LANDSAT_MSS, 'L2_RAW': _LANDSAT_MSS, 'L3_RAW': _LANDSAT_MSS,
    'L4_SR': _LANDSAT_SR, 'L5_SR': _LANDSAT_SR, 'L7_SR': _LANDSAT_SR,
    'L8_SR': _LANDSAT_SR, 'L9_SR': _LANDSAT_SR,
    'S2_SR': frozenset({'B', 'G', 'R', 'RE1', 'RE2', 'RE3', 'RE4', 'N', 'S1', 'S2'}),
}


def build_entries(catalog):
    """
    Engine catalog -> ordered list of predictor entries:
        id          what the API and the frontend use
        name        the engine's catalog key
        band        the band name in the stacked image
        engine_key  'sentinel1' / 'palsar' for radar, else None
    Entries the backend cannot route to the engine (an unknown type or radar
    band) are left out.
    """
    entries = []
    for name, meta in catalog.items():
        ptype = meta.get('type', 'spectral')
        engine_key = None
        if ptype == 'spectral':
            pid, band = name, name
        elif ptype == 'terrain':
            pid, band = name.upper(), name.lower()
        elif ptype == 'radar' and name in RADAR:
            pid, engine_key, band = RADAR[name]
        elif ptype == 'distance':
            pid, band = name.upper(), name
        else:
            continue

        long_name = meta.get('long_name', name)
        entries.append({
            'id': pid,
            'name': name,
            'type': ptype,
            'group': CATEGORY_GROUPS.get(meta.get('category')) or TYPE_GROUPS.get(ptype, 'other'),
            'band': band,
            'engine_key': engine_key,
            'label': long_name if ptype == 'distance' else name,
            'long_name': long_name,
            'description': meta.get('description', ''),
            'required_bands': list(meta.get('required_bands') or []),
        })
    return entries


def _entries_by_id(catalog):
    return {entry['id']: entry for entry in build_entries(catalog)}


def _check_availability(entry, availability, sensor_code=None, sensor_family=None):
    """-> (available, reason, reason_code); reason_code is 'sensor', 'date', 'bands' or None."""
    info = (availability or {}).get(entry['name']) or {}
    if not info.get('available', True):
        compatibility = info.get('sensor_compatibility', 'ALL')
        wrong_sensor = sensor_family is not None and compatibility not in ('ALL', sensor_family)
        return False, info.get('reason', ''), 'sensor' if wrong_sensor else 'date'

    # The engine checks sensor family and dates only. It would silently skip an
    # index whose bands the composite does not have, so report that up front.
    sensor_bands = SENSOR_BANDS.get(sensor_code)
    if sensor_bands is not None:
        missing = [band for band in entry['required_bands'] if band not in sensor_bands]
        if missing:
            return False, 'Requires bands this satellite does not provide ({})'.format(', '.join(missing)), 'bands'

    return True, '', None


def _conflicts(pid):
    return [b if a == pid else a for a, b in CONFLICTING_PREDICTORS if pid in (a, b)]


def build_listing(catalog, availability, sensor_code=None, sensor_family=None, selected=None):
    """What GET /luma/predictor/available returns: grouped predictors plus the saved selection."""
    groups = {}
    for entry in build_entries(catalog):
        available, reason, reason_code = _check_availability(entry, availability, sensor_code, sensor_family)
        groups.setdefault(entry['group'], []).append({
            'id': entry['id'],
            'label': entry['label'],
            'long_name': entry['long_name'],
            'description': entry['description'],
            'type': entry['type'],
            'available': available,
            'reason': reason,
            'reason_code': reason_code,
            'conflicts_with': _conflicts(entry['id']),
        })
    return {
        'groups': [{'key': key, 'predictors': groups[key]} for key in GROUP_ORDER if key in groups],
        'selected': list(selected or []),
    }


def available_ids(catalog, availability, sensor_code=None, sensor_family=None):
    """Ids of every predictor the session can use, in catalog order."""
    return [
        entry['id'] for entry in build_entries(catalog)
        if _check_availability(entry, availability, sensor_code, sensor_family)[0]
    ]


def normalize_selection(predictors):
    """Request value -> list of ids, duplicates dropped, order kept."""
    if predictors is None:
        return []
    if not isinstance(predictors, (list, tuple)):
        raise ValueError('invalid input: predictor, format: list')
    ids = []
    for predictor in predictors:
        if not isinstance(predictor, str):
            raise ValueError('invalid input: predictor, format: list of strings')
        if predictor not in ids:
            ids.append(predictor)
    return ids


def validate_selection(ids, catalog, availability, sensor_code=None, sensor_family=None, allow_conflicts=False):
    """
    Raise ValueError when a selection cannot be used for this session.
    allow_conflicts: skip the conflicting-pair rule (optimizer candidates).
    """
    entries = _entries_by_id(catalog)
    for pid in ids:
        entry = entries.get(pid)
        if entry is None:
            if pid in LEGACY_SPECTRAL:
                continue
            raise ValueError('invalid input: predictor, format: list of valid predictor names')
        available, reason, _ = _check_availability(entry, availability, sensor_code, sensor_family)
        if not available:
            raise ValueError('invalid input: predictor, {} is not available: {}'.format(pid, reason))
    if allow_conflicts:
        return
    for a, b in CONFLICTING_PREDICTORS:
        if a in ids and b in ids:
            raise ValueError('invalid input: predictor, {} and {} cannot be selected together'.format(a, b))


def build_engine_config(ids, catalog):
    """
    Selected ids -> the predictor_config stored on the session, in the shape
    luma_ge PredictorCalculation.compute_predictors() reads. Two extra keys
    are the backend's own:
        selected            the ids as the user picked them
        composite_indices   indices needing the thermal band; the engine maps
                            spectral indices over the optical collection, which
                            has none, so the backend computes these itself
    """
    entries = _entries_by_id(catalog)
    individual = {'spectral_indices': []}
    for entry in entries.values():
        if entry['type'] in ('terrain', 'distance'):
            individual[entry['band']] = False

    sentinel1, palsar, composite_indices = [], [], []
    terrain = False
    for pid in ids:
        entry = entries.get(pid)
        if entry is None:
            # legacy spectral index, computed by its spyndex name
            individual['spectral_indices'].append(pid)
        elif entry['type'] == 'spectral':
            if THERMAL_BAND in entry['required_bands']:
                composite_indices.append(entry['name'])
            else:
                individual['spectral_indices'].append(entry['name'])
        elif entry['type'] == 'terrain':
            individual[entry['band']] = True
            terrain = True
        elif entry['type'] == 'radar':
            (sentinel1 if entry['engine_key'] == 'sentinel1' else palsar).append(entry['band'])
        elif entry['type'] == 'distance':
            individual[entry['band']] = True

    return {
        'selected': list(ids),
        'individual_predictors': individual,
        'terrain': terrain,
        'spectral_indices': list(individual['spectral_indices']),
        'index_coefficients': {},
        'sentinel1': sentinel1,
        'palsar': palsar,
        'composite_indices': composite_indices,
    }


def selection_bands(ids, catalog):
    """
    Selected ids -> [{'id', 'band', 'label', 'type', 'group'}] in selection
    order, 'band' being the band name in the stacked image. Unknown ids are
    left out.
    """
    entries = _entries_by_id(catalog)
    selection = []
    for pid in ids:
        entry = entries.get(pid)
        if entry is not None:
            selection.append({key: entry[key] for key in ('id', 'band', 'label', 'type', 'group')})
        elif pid in LEGACY_SPECTRAL:
            selection.append({
                'id': pid, 'band': pid, 'label': pid,
                'type': 'spectral', 'group': LEGACY_SPECTRAL[pid],
            })
    return selection


def selected_ids(predictor_config):
    """Ids saved on a session, including configs saved before 'selected' existed."""
    config = predictor_config or {}
    if isinstance(config.get('selected'), list):
        return list(config['selected'])
    individual = config.get('individual_predictors') or {}
    ids = [key.upper() for key in ('elevation', 'slope', 'aspect') if individual.get(key)]
    ids += list(individual.get('spectral_indices') or config.get('spectral_indices') or [])
    return ids


def selected_labels(predictor_config, catalog):
    """Display names of the saved selection, for summaries and export metadata."""
    entries = _entries_by_id(catalog)
    return [entries[pid]['label'] if pid in entries else pid for pid in selected_ids(predictor_config)]


def build_recommendation(selection, ranking, support, importances):
    """
    Result of the engine's RFE_CV -> the recommendation the API returns.

    selection:   selection_bands() entries of the candidates in the stack
    ranking:     RFE_CV.get_ranking()         {band: rank}, 1 = kept
    support:     RFE_CV.get_support()         {band: kept or not}
    importances: RFE_CV.feature_importances_  {band: importance}, 0 when dropped

    The elimination runs over composite bands and candidates together, so the
    ranking lists both; only predictors can be recommended, because the
    composite bands are always part of the classification.

    -> {'recommended': [ids], 'conflict_dropped': [ids], 'ranking': [rows]}
    """
    by_band = {item['band']: item for item in selection}
    importances = importances or {}

    rows = []
    for band, rank in ranking.items():
        item = by_band.get(band)
        rows.append({
            'band': band,
            'kind': 'predictor' if item else 'band',
            'id': item['id'] if item else None,
            'label': item['label'] if item else band,
            'rank': int(rank),
            'selected': bool(support.get(band, False)),
            'importance': float(importances.get(band) or 0.0),
        })
    rows.sort(key=lambda row: (row['rank'], -row['importance'], row['band']))

    recommended = [row['id'] for row in rows if row['kind'] == 'predictor' and row['selected']]
    conflict_dropped = []
    for a, b in CONFLICTING_PREDICTORS:
        if a in recommended and b in recommended:
            weaker = a if recommended.index(a) > recommended.index(b) else b
            recommended.remove(weaker)
            conflict_dropped.append(weaker)

    return {'recommended': recommended, 'conflict_dropped': conflict_dropped, 'ranking': rows}


def recommendation_inputs(sensor, start_date, end_date, cloud_cover, spatial_resolution,
                          training_counts, training_modified):
    """
    What a recommendation was computed from. Stored next to it, in a form that
    survives JSON storage, and compared later to tell whether it is stale.
    """
    return {
        'sensor': sensor,
        'start_date': start_date,
        'end_date': end_date,
        'cloud_cover': cloud_cover,
        'spatial_resolution': spatial_resolution,
        'training_counts': {str(class_id): int(count) for class_id, count in (training_counts or {}).items()},
        'training_modified': training_modified,
    }


def public_recommendation(stored, current_inputs):
    """Saved recommendation as the API returns it: no 'inputs', plus 'stale'. None when nothing is saved."""
    if not stored:
        return None
    public = {key: value for key, value in stored.items() if key != 'inputs'}
    public['stale'] = stored.get('inputs') != current_inputs
    return public
