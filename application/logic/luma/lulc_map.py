import ee
import geopandas as gpd
import geemap
import json

from flask import current_app

from application import db
from application.logic.geos.aoi import converter
from application.utils.common import AppMessageException

from luma_ge.data_acquisition import Reflectance_Data, Reflectance_Stats, final_Image
from luma_ge.classification import FeatureExtraction, Generate_LULC
from luma_ge.classification_scheme import LULC_Scheme_Manager
from luma_ge.sample_data_quality import sample_quality, spectral_plotter

PREBUILT_SCHEME = 'RESTORE+ Project'

def pack(data):
    return json.dumps(data) + "\n"

def forge_process(step, data):
    data = {
        'process': processes[step]['name'],
        'data': data,
        'w': total_w,
        'a': processes[step]['w'],
        'next': processes[step+1]['name'],
    }
    return pack(data)

processes = [
    { 'name': 'preparation', 'w': 0.1 },
    { 'name': 'get optical data', 'w': 0.1 },
    { 'name': 'get thermal bands', 'w': 2.0 },
    { 'name': 'check image count', 'w': 8.0 },
    { 'name': 'create image composite', 'w': 0.1 },
    { 'name': 'get training data', 'w': 0.1 },
    { 'name': 'split training data', 'w': 3.0 },
    { 'name': 'model training & classification', 'w': 0.1 },
    { 'name': 'visualization', 'w': 3.0 },
    { 'name': 'calculate lulc composition', 'w': 1.0 },
    { 'name': 'sample data quality', 'w': 5.0 },
    { 'name': 'feature importance', 'w': 2.0 },
    { 'name': 'evaluate model quality', 'w': 10.0 },
    { 'name': 'get download url', 'w': 2.5 },
    { 'name': 'end', 'w': 0.1 },
]
total_w = sum([p['w'] for p in processes])

def _log_step_failure(stage, e):
    current_app.logger.error('luma generate: {} failed: {}'.format(stage, e))

def generate(known_session, known_aoi, aoi, luma, classes):
    step = 0

    optical_data = luma.landsat_version
    thermal_data = optical_data.replace('_SR', '_TOA')
    start_date = luma.start_date.strftime('%Y-%m-%d')
    end_date = luma.end_date.strftime('%Y-%m-%d')
    yield forge_process(step, { 'processes': processes })

    collection = None
    thermal_collection = None
    image = None
    train_gdf = None
    roi_ee = None
    train_data_split = None
    testing_data_split = None
    classification_result = None
    trained_model = None
    layers = []
    lulc_composition = []
    class_property = 'class_id'
    class_name_property = 'class_name'
    pixel_size = 30
    split_ratio = 0.5
    scale = 30
    reflectance = Reflectance_Data()
    lulc = Generate_LULC()

    #region get optical data
    try:
        collection, _meta = reflectance.get_optical_data(
            aoi=aoi,
            start_date=start_date,
            end_date=end_date,
            optical_data=optical_data,
            cloud_cover=luma.cloud_cover,
            verbose=False,
            compute_detailed_stats=False
        )
    except Exception as e:
        _log_step_failure('get optical data', e)
    step = step + 1
    yield forge_process(step, {})
    #endregion

    #region get thermal data
    try:
        if optical_data not in ['L1_RAW', 'L2_RAW', 'L3_RAW']:
            thermal_collection, _meta = reflectance.get_thermal_bands(
                aoi=aoi,
                start_date=start_date,
                end_date=end_date,
                thermal_data=thermal_data,
                cloud_cover=luma.cloud_cover,
                verbose=False,
                compute_detailed_stats=False
            )
    except Exception as e:
        _log_step_failure('get thermal bands', e)
    step = step + 1
    yield forge_process(step, {})
    #endregion

    #region check image count
    try:
        if collection is not None:
            stats = Reflectance_Stats()
            detailed_stats = stats.get_collection_statistics(collection, compute_stats=True, print_report=True)
            total_images = detailed_stats.get('total_images', 0) or detailed_stats.get('num_images', 0)
            if not total_images:
                try:
                    total_images = int(collection.size().getInfo())
                except:
                    total_images = 0
            if total_images <= 0:
                collection = None
    except Exception as e:
        _log_step_failure('check image count', e)
        collection = None
    step = step + 1
    yield forge_process(step, {})
    #endregion

    #region create image composite
    try:
        if collection is not None:
            image_processor = final_Image()
            if thermal_collection is not None:
                thermal_median = thermal_collection.median().clip(aoi)
                composite = image_processor.get_temporal_composite(collection, aoi, reducer='median', verbose=False)
                composite = composite.addBands(thermal_median).toFloat()
            else:
                composite = image_processor.get_temporal_composite(collection, aoi, reducer='median', verbose=False).toFloat()
            image = composite
    except Exception as e:
        _log_step_failure('create image composite', e)
    step = step + 1
    yield forge_process(step, {})
    #endregion

    #region get training data
    try:
        train_gdf = gpd.read_postgis(
            db.text(
            '''
            select
                class_id,
                class_name,
                class_color,
                geom geometry
            from luma_training_data
            where session_id = :session_id
            order by class_id
            '''
            ),
            db.engine,
            geom_col='geometry',
            params={'session_id': known_session.id}
        )
    except Exception as e:
        _log_step_failure('get training data', e)
    step = step + 1
    yield forge_process(step, {})
    #endregion

    #region stratified split training data
    try:
        if train_gdf is not None and image is not None:
            roi_ee = converter.convert_roi_gdf(train_gdf)
            fe = FeatureExtraction()
            train_data_split, testing_data_split = fe.stratified_split(
                roi=roi_ee,
                image=image,
                class_prop=class_property,
                pixel_size=pixel_size,
                train_ratio=split_ratio,
            )
    except Exception as e:
        _log_step_failure('split training data', e)
    step = step + 1
    yield forge_process(step, {})
    #endregion

    #region classification
    try:
        if train_data_split is not None and image is not None:
            classification_result, trained_model = lulc.hard_classification(
                training_data=train_data_split,
                class_property=class_property,
                image=image,
                ntrees=300,
                v_split=None,
                min_leaf=2,
                return_model=True
            )
    except Exception as e:
        _log_step_failure('classification', e)
    step = step + 1
    yield forge_process(step, {})
    #endregion

    #region visualization
    try:
        Map = geemap.Map()
        Map.centerObject(aoi, 8)
        if classification_result is not None and train_gdf is not None:
            unique_df = train_gdf[['class_id', 'class_color']].drop_duplicates('class_id').sort_values('class_id')
            vis_params = {
                'min': int(unique_df['class_id'].min()),
                'max': int(unique_df['class_id'].max()),
                'palette': unique_df['class_color'].tolist()
            }
            Map.addLayer(classification_result, vis_params, 'Land Cover Classification')

        try:
            manager = LULC_Scheme_Manager()
            manager.load_default_scheme(PREBUILT_SCHEME)
            scheme_df = manager.get_dataframe()
            selection = manager.store_classes_of_interest(
                scheme_name=PREBUILT_SCHEME,
                classes_of_interest=[int(c.class_id) for c in classes],
            )
            prebuilt = lulc.classify_from_prebuilt(
                scheme_name=PREBUILT_SCHEME,
                aoi=aoi,
                year=luma.start_date.year,
                scheme_classes=manager.classes,
            )
            reclassified_map, _info = lulc.reclassify_map_by_classes(
                classification_map=prebuilt['final_map'],
                classification_df=scheme_df,
                selected_classes=selection,
            )
            selection_df = scheme_df[scheme_df['ID'].isin([int(c.class_id) for c in classes])].sort_values('ID')
            prebuilt_vis = {
                'min': int(selection_df['ID'].min()),
                'max': int(selection_df['ID'].max()),
                'palette': selection_df['Color Palette'].tolist()
            }
            Map.addLayer(reclassified_map, prebuilt_vis, 'Prebuilt LULC ({} {})'.format(prebuilt['scheme'], prebuilt['year_used']))
        except Exception as e:
            _log_step_failure('prebuilt clip layer', e)

        for m in Map.ee_layer_dict.keys():
            d = Map.ee_layer_dict[m]
            layers.append({ 'name': m, 'url': d['ee_layer'].url })
    except Exception as e:
        _log_step_failure('visualization', e)
    step = step + 1
    yield forge_process(step, { 'layers': layers })
    #endregion

    #region calculate lulc composition
    try:
        if classification_result is not None:
            hist = classification_result.select('classification').reduceRegion(
                reducer=ee.Reducer.frequencyHistogram(),
                geometry=aoi,
                scale=scale,
                maxPixels=1e13
            ).get('classification').getInfo()
            pixel_area = scale * scale
            area_dict = {int(k): v * pixel_area for k, v in (hist or {}).items()}
            total_area = sum(area_dict.values())
            if total_area > 0:
                for c in classes:
                    area = area_dict.get(c.class_id, 0)
                    if area > 0:
                        lulc_composition.append({
                            'class_id': c.class_id,
                            'class_name': c.class_name,
                            'class_color': c.class_color,
                            'area_m2': area,
                            'proportion': area / total_area * 100
                        })
                lulc_composition.sort(key=lambda x: x['proportion'], reverse=True)
    except Exception as e:
        _log_step_failure('lulc composition', e)
    step = step + 1
    yield forge_process(step, { 'lulc_composition': lulc_composition })
    #endregion

    #region sample data quality
    lowest_separability = { 'min_td': 0, 'result_dict': [] }
    try:
        if roi_ee is not None and image is not None:
            analyzer = sample_quality(
                training_data=roi_ee,
                image=image,
                class_property=class_property,
                region=aoi,
                class_name_property=class_name_property,
            )
            analyzer.get_sample_stats_df()
            pixel_extract = analyzer.extract_spectral_values(scale=scale, max_pixels_per_class=5000)
            analyzer.get_sample_pixel_stats_df(pixel_extract)
            analyzer.get_separability_df(pixel_extract, method='TD')
            lowest_sep = analyzer.lowest_separability(pixel_extract, method='TD')
            min_td = lowest_sep['TD_Distance'].min()
            lowest_sep_sorted = lowest_sep.sort_values(by='TD_Distance')
            lowest_sep_filtered = lowest_sep_sorted[lowest_sep_sorted['TD_Distance'] < 1.8]
            lowest_separability = {
                'min_td': min_td,
                'result_dict': lowest_sep_filtered.to_dict(orient='records')
            }
    except Exception as e:
        _log_step_failure('sample data quality', e)
    step = step + 1
    yield forge_process(step, { 'lowest_separability': lowest_separability })
    #endregion

    #region feature importance
    feature_importance = []
    try:
        if trained_model is not None and train_data_split is not None:
            importance_df = lulc.get_feature_importance(
                trained_model,
                training_data=train_data_split,
                class_property=class_property
            )
            feature_importance = importance_df.to_dict('records')
    except Exception as e:
        _log_step_failure('feature importance', e)
    step = step + 1
    yield forge_process(step, { 'feature_importance': feature_importance })
    #endregion

    #region model quality
    model_quality_payload = {
        'overall_accuracy': 0,
        'kappa': 0,
        'average_f1_score': 0,
        'gmean_score': 0
    }
    try:
        if trained_model is not None and testing_data_split is not None:
            model_quality = lulc.evaluate_model(
                trained_model=trained_model,
                test_data=testing_data_split,
                class_property=class_property
            )
            f1s = model_quality.get('f1_scores', []) or []
            avg_f1 = sum(f1s) / len(f1s) if f1s else 0
            model_quality_payload = {
                'overall_accuracy': model_quality.get('overall_accuracy', 0) * 100,
                'kappa': model_quality.get('kappa', 0),
                'average_f1_score': avg_f1,
                'gmean_score': model_quality.get('overall_gmean', 0)
            }
    except Exception as e:
        _log_step_failure('evaluate model quality', e)
    step = step + 1
    yield forge_process(step, { 'model_quality': model_quality_payload })
    #endregion

    #region export image
    download_url = ''
    try:
        if classification_result is not None:
            export_image = classification_result.toInt()
            download_url = export_image.getDownloadURL({
                'name': 'LULC_{sensor}_{start_date}_{end_date}'.format(sensor=optical_data, start_date=start_date, end_date=end_date),
                'crs': 'EPSG:4326',
                'scale': 30,
                'region': aoi,
                'fileFormat': 'GEO_TIFF',
                'formatOptions': {'cloudOptimized': True, 'noData': 0}
            })
    except Exception as e:
        _log_step_failure('get download url', e)
    step = step + 1
    yield forge_process(step, { 'download_url': download_url })
    #endregion
