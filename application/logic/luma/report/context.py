"""
Builds the report template's fields from one run's saved results.

Pure: no database, no Earth Engine. `results` is the saved output of map
generation plus the separability and thematic checks:

    session_id, generated_at (ISO, UTC)
    luma           sensor, start_date, end_date, cloud_cover, spatial_resolution,
                   ntrees, min_leaf, split_ratio, use_predictor, predictor_config
    classes        [{class_id, class_name, class_color}]
    aoi            {area_size (ha), regency_code, geojson}
    training       {points: [{class_id, lon, lat}]}
    scenes         [{id, t (ms), cloud, tile | path + row}]
    lulc_composition, model_quality       as streamed by lulc_map.generate
    separability                          as returned by separability_summary.build_summary (or None)
    separability_pixel_counts             {class_id: valid pixels}
    separability_pairs                    [{a, b, td}] lowest TD first
    thematic                              as returned by thematic.assess (or None)

`meta` holds what the app does not store today (how the AOI was defined,
uploaded file names, the area's name, versions, account, project). Figures are
made separately (figures.py); pdf.py lays the fields and figures out.
"""
from datetime import datetime, timezone

from shapely.geometry import shape

from . import rules
from .formatting import coord_id, date_id, date_range_id, datetime_wib, hex_code, num

SENSOR_NAMES = {
    'S2_SR': 'Sentinel-2',
    'L9_SR': 'Landsat 9', 'L8_SR': 'Landsat 8', 'L7_SR': 'Landsat 7',
    'L5_SR': 'Landsat 5', 'L4_SR': 'Landsat 4',
}

AOI_METHOD_LABELS = {
    'admin': 'memilih batas administrasi',
    'upload': 'mengunggah berkas poligon',
    'draw': 'menggambar poligon',
}
SCHEME_LABELS = {'default': 'skema bawaan Epistem', 'custom': 'skema klasifikasi buatan pengguna'}
SAMPLE_SOURCE_LABELS = {
    'upload': 'diunggah oleh pengguna',
    'onscreen': 'dibuat langsung di peta oleh pengguna (on-screen sampling)',
}

# code -> (full name, what it helps recognise). The second column is report copy:
# only the entries that appear in the example report are filled in.
PREDICTOR_INFO = {
    'NDVI': ('Normalized Difference Vegetation Index', 'Kehijauan / kerapatan vegetasi'),
    'EVI': ('Enhanced Vegetation Index', 'Vegetasi rapat, mengurangi efek atmosfer'),
    'MNDWI': ('Modified Normalized Difference Water Index', 'Air dan lahan basah'),
    'NDBI': ('Normalized Difference Built-up Index', 'Lahan terbangun dan terbuka'),
    'MSAVI': ('Modified Soil-Adjusted Vegetation Index', '—'),
    'OSAVI': ('Optimized Soil-Adjusted Vegetation Index', '—'),
    'SAVI': ('Soil-Adjusted Vegetation Index', '—'),
    'ARVI': ('Atmospherically Resistant Vegetation Index', '—'),
    'GNDVI': ('Green Normalized Difference Vegetation Index', '—'),
    'GBNDVI': ('Green-Blue Normalized Difference Vegetation Index', '—'),
    'NDWI': ('Normalized Difference Water Index', '—'),
}
TERRAIN_INFO = {
    'elevation': ('Elevation', 'Ketinggian permukaan', 'Perbedaan dataran rendah dan tinggi', 'NASADEM'),
    'slope': ('Slope', 'Kemiringan lereng', 'Bentuk medan (datar–curam)', 'Turunan DEM'),
    'aspect': ('Aspect', 'Arah hadap lereng', '—', 'Turunan DEM'),
}


def _parse_date(text):
    return datetime.strptime(text[:10], '%Y-%m-%d')


def _top_confusions(matrix, names, limit=3):
    cells = [(matrix[i][j], i, j)
             for i in range(len(matrix)) for j in range(len(matrix[i]))
             if i != j and matrix[i][j] > 0]
    cells.sort(key=lambda c: (-c[0], c[1], c[2]))
    return [{'actual': names.get(i, 'Kelas {}'.format(i)),
             'predicted': names.get(j, 'Kelas {}'.format(j)),
             'count': n} for n, i, j in cells[:limit]]


def _row_total(matrix, class_id):
    return int(sum(matrix[class_id])) if class_id < len(matrix) else 0


def _predictors(luma, sensor_name):
    if not luma.get('use_predictor'):
        return []
    cfg = luma.get('predictor_config') or {}
    individual = cfg.get('individual_predictors') or {}
    rows = []
    for code in (cfg.get('spectral_indices') or individual.get('spectral_indices') or []):
        name, measures = PREDICTOR_INFO.get(code, (code, '—'))
        rows.append({'code': code, 'name': name, 'measures': measures, 'source': sensor_name})
    for key, (code, name, measures, source) in TERRAIN_INFO.items():
        if individual.get(key):
            rows.append({'code': code, 'name': name, 'measures': measures, 'source': source})
    return rows


def build_context(results, meta):
    luma = results['luma']
    classes = results['classes']
    names = {c['class_id']: c['class_name'] for c in classes}
    colors = {c['class_id']: hex_code(c['class_color']) for c in classes}
    sensor_name = SENSOR_NAMES.get(luma['sensor'], luma['sensor'])
    resolution = luma['spatial_resolution']

    # ---- period
    start, end = _parse_date(luma['start_date']), _parse_date(luma['end_date'])
    full_year = (start.year == end.year and (start.month, start.day) == (1, 1)
                 and (end.month, end.day) == (12, 31))
    period = {
        'date_range': date_range_id(start, end),
        'period_label': str(start.year) if full_year else date_range_id(start, end),
        'interval_label': 'per tahun' if full_year else 'rentang tanggal khusus',
    }

    # ---- AOI
    geom = shape(results['aoi']['geojson'])
    area_ha = float(results['aoi']['area_size'])
    method = meta.get('aoi_method') or ('admin' if results['aoi'].get('regency_code') else 'draw')
    aoi = {
        'display_name': meta.get('aoi_display_name') or 'wilayah pemetaan',
        'area_ha': num(area_ha),
        'method': method,
        'method_label': AOI_METHOD_LABELS[method],
        'admin_name': meta.get('aoi_admin_name') or '',
        'file_name': meta.get('aoi_file_name') or '',
        'admin_overlap': meta.get('aoi_admin_overlap') or '',
        'centroid': coord_id(geom.centroid.y, geom.centroid.x),
        'resolution_label': '{r} m × {r} m'.format(r=resolution),
        'pixel_area_ha': num(resolution * resolution / 10000.0, 2),
        'crs': 'WGS 84 (EPSG:4326)',
    }

    # ---- imagery
    scenes = sorted(results.get('scenes') or [], key=lambda s: s.get('t') or 0)
    clouds = [s['cloud'] for s in scenes if s.get('cloud') is not None]
    scene_rows = []
    for i, s in enumerate(scenes, start=1):
        if s.get('tile'):
            where = s['tile']
        elif s.get('path') is not None:
            where = '{:03d}/{:03d}'.format(int(s['path']), int(s['row']))
        else:
            where = '–'
        scene_rows.append({
            'no': i,
            'scene_id': s.get('id') or '–',
            'date': date_id(datetime.fromtimestamp(s['t'] / 1000.0, tz=timezone.utc)) if s.get('t') else '–',
            'path_row': where,
            'cloud_pct': num(s['cloud'], 2) if s.get('cloud') is not None else '–',
        })
    imagery = {
        'sensor': sensor_name,
        'scene_count': len(scenes),
        'cloud_max_pct': luma['cloud_cover'],
        'cloud_mean': num(sum(clouds) / len(clouds), 1) if clouds else '–',
        'cloud_min': num(min(clouds), 1) if clouds else '–',
        'cloud_max': num(max(clouds), 1) if clouds else '–',
        'scenes': scene_rows,
    }

    # ---- classification scheme
    scheme = meta.get('scheme') or 'custom'
    classif = {
        'scheme': scheme,
        'scheme_label': SCHEME_LABELS[scheme],
        'n_classes': len(classes),
        'file_name': meta.get('scheme_file_name') or '',
        'classes': [{'id': c['class_id'], 'name': c['class_name'], 'hex': colors[c['class_id']],
                     'description': (meta.get('class_descriptions') or {}).get(c['class_id'], '—')}
                    for c in classes],
    }

    # ---- sample data
    points = results['training']['points']
    pixel_counts = {int(k): int(v) for k, v in (results.get('separability_pixel_counts') or {}).items()}
    per_class = []
    for c in classes:
        n_samples = sum(1 for p in points if p['class_id'] == c['class_id'])
        per_class.append({'id': c['class_id'], 'name': c['class_name'], 'hex': colors[c['class_id']],
                          'n_samples': n_samples, 'n_pixels': pixel_counts.get(c['class_id'], 0)})
    sample_source = meta.get('sample_source') or 'onscreen'
    sample = {
        'source': 'default' if sample_source == 'default' else 'user',
        'source_label': SAMPLE_SOURCE_LABELS.get(sample_source, ''),
        'file_name': meta.get('sample_file_name') or '',
        'ref_dataset_label': meta.get('ref_dataset_label') or '',
        'total_samples': len(points),
        'total_pixels': sum(pixel_counts.values()),
        'per_class': per_class,
    }

    # ---- separability
    sep = results.get('separability')
    separability = None
    low_pixel_classes = []
    if sep:
        low_pixel_classes = [c['class_name'] for c in sep.get('low_sample_classes', [])]
        separability = {
            'n_pairs': sep['pair_counts']['total'],
            'n_good': sep['pair_counts']['good'],
            'n_weak': sep['pair_counts']['weak'],
            'n_poor': sep['pair_counts']['poor'],
            'mean_td': num(sep['mean_td'], 2),
            'category_label': rules.TD_OVERALL_LABELS.get(sep['overall'], sep['overall']),
            'hardest_pairs': [{'a': p['a'], 'b': p['b'], 'td': num(p['td'], 2), 'label': rules.td_label(p['td'])}
                              for p in (results.get('separability_pairs') or [])[:3]],
            'low_pixel_classes': ', '.join(low_pixel_classes),
        }

    # ---- model parameters
    train_pct = int(round(float(luma['split_ratio']) * 100))
    predictors = _predictors(luma, sensor_name)
    params = {
        'locked': bool(meta.get('params_locked')),
        'n_trees': luma['ntrees'],
        'min_leaf': luma['min_leaf'],
        'train_pct': train_pct,
        'val_pct': 100 - train_pct,
        'predictors': predictors,
        'predictor_codes': ', '.join(p['code'] for p in predictors) or 'tanpa prediktor tambahan',
    }

    # ---- result: composition
    comp = results.get('lulc_composition') or []
    total_m2 = sum(c['area_m2'] for c in comp)
    comp_rows = [{'rank': i, 'name': c['class_name'], 'hex': hex_code(c['class_color']),
                  'area_ha': num(c['area_m2'] / 10000.0), 'pct': num(c['proportion'], 1)}
                 for i, c in enumerate(comp, start=1)]
    top = [{'name': r['name'], 'area_ha': r['area_ha'], 'pct': r['pct']} for r in comp_rows[:3]]
    while len(top) < 2:  # the template reads top[0] and top[1] unconditionally
        top.append({'name': '–', 'area_ha': '0', 'pct': '0'})
    total_ha = total_m2 / 10000.0
    nodata_ha = area_ha - total_ha
    has_nodata = nodata_ha > 0.005 * area_ha  # ignore the pixel-edge rounding
    veg = rules.vegetation_split(classes, comp)
    result = {
        'top': top,
        'top3_pct': num(sum(c['proportion'] for c in comp[:3]), 1),
        'small_classes': ', '.join(c['class_name'] for c in comp if c['proportion'] < 1),
        'composition': comp_rows,
        'total_ha': num(total_ha),
        'nodata_ha': num(nodata_ha) if has_nodata else '',
        'nodata_pct': num(nodata_ha / area_ha * 100, 1) if has_nodata else '',
        'has_veg_split': veg is not None,
        'veg_pct': num(veg['veg_pct'], 1) if veg else '',
        'nonveg_pct': num(veg['nonveg_pct'], 1) if veg else '',
    }

    # ---- model accuracy (confusion matrix is indexed by class id: rows actual, columns predicted)
    mq = results.get('model_quality') or {}
    mq_matrix = mq.get('confusion_matrix') or []
    mq_per = {p['class_id']: p for p in (mq.get('per_class') or [])}
    model_oa = mq.get('overall_accuracy', 0)
    model_acc = {
        'oa': num(model_oa, 1),
        'level_label': rules.accuracy_level(model_oa)[1],
        'kappa': num(mq.get('kappa', 0), 3),
        'f1': num(mq.get('average_f1_score', 0), 3),
        'gmean': num(mq.get('gmean_score', 0), 3),
        'n_val_samples': int(sum(sum(r) for r in mq_matrix)),
        'confusions': _top_confusions(mq_matrix, names),
        'classes': [{'name': c['class_name'],
                     'n': _row_total(mq_matrix, c['class_id']),
                     'pa': num(mq_per.get(c['class_id'], {}).get('recall', 0) * 100, 1),
                     'ua': num(mq_per.get(c['class_id'], {}).get('precision', 0) * 100, 1),
                     'f1': num(mq_per.get(c['class_id'], {}).get('f1_score', 0), 2)}
                    for c in classes],
    }

    # ---- thematic accuracy
    th = results.get('thematic')
    thematic = {'done': False}
    thematic_oa = None
    if th:
        th_matrix = th['confusion_matrix']
        th_per = {p['class_id']: p for p in th['per_class']}
        thematic_oa = th['overall_accuracy'] * 100
        lo, hi = th['overall_accuracy_ci']
        thematic = {
            'done': True,
            'file_name': meta.get('validation_file_name') or '',
            'n_points': th['n_total'],
            'n_correct': th['n_correct'],
            'n_wrong': th['n_total'] - th['n_correct'],
            'oa': num(thematic_oa, 1),
            'ci': '{}% – {}%'.format(num(lo * 100, 1), num(hi * 100, 1)),
            'kappa': num(th['kappa'], 3),
            'error_rate': num(100 - thematic_oa, 1),
            'level_label': rules.accuracy_level(thematic_oa)[1],
            'confusions': _top_confusions(th_matrix, names),
            'classes': [{'name': c['class_name'],
                         'n': _row_total(th_matrix, c['class_id']),
                         'pa': num(th_per.get(c['class_id'], {}).get('producer_accuracy', 0) * 100, 1),
                         'ua': num(th_per.get(c['class_id'], {}).get('user_accuracy', 0) * 100, 1),
                         'f1': num(th_per.get(c['class_id'], {}).get('f1_score', 0), 2)}
                        for c in classes],
        }

    # ---- report header
    account = meta.get('account') or {}
    project = meta.get('project') or {}
    issued = meta.get('issued') or datetime.now(timezone.utc)
    generated = datetime.fromisoformat(results['generated_at']) if results.get('generated_at') else issued
    report = {
        'map_name': project.get('name') or meta.get('map_name') or 'Peta Tutupan Lahan {}'.format(period['period_label']),
        'prepared_by': account.get('fullname') or account.get('email') or '–',
        'organization': account.get('organization_name') or '',
        'contact': account.get('email') or '–',
        'project_id': project.get('id') or '–',
        'session_id': results['session_id'],
        'issued_date': date_id(issued),
        'issued_year': issued.year,
        'generated_at': datetime_wib(generated),
        'report_version': meta.get('report_version') or '1.0',
        'luma_version': meta.get('luma_version') or '–',
        'ge_version': meta.get('ge_version') or '–',
        'map_url': meta.get('map_url') or '–',
    }

    extra_references = []
    if luma['sensor'] == 'S2_SR':
        extra_references.append('European Space Agency. Copernicus Sentinel-2 Surface Reflectance (Harmonized). '
                                'Diakses melalui Google Earth Engine.')

    return {
        'report': report,
        'aoi': aoi,
        'period': period,
        'imagery': imagery,
        'classif': classif,
        'sample': sample,
        'separability': separability,
        'params': params,
        'result': result,
        'model_acc': model_acc,
        'thematic': thematic,
        'fitness': rules.fitness(model_oa, thematic_oa),
        'flags': rules.data_flags(low_pixel_classes),
        'extra_references': extra_references,
    }
