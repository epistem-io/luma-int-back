import ee
import geopandas as gpd
import geemap
import json

from application import db
from application.logic.geos.aoi import converter
from application.utils.common import AppMessageException

from luma_ge.data_acquisition import Reflectance_Data, Reflectance_Stats, final_Image
from luma_ge.classification import FeatureExtraction, Generate_LULC

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
    { 'name': 'feature importance', 'w': 2.0 },
    { 'name': 'evaluate model quality', 'w': 10.0 },
    { 'name': 'get download url', 'w': 2.5 },
    { 'name': 'end', 'w': 0.1 },
]
total_w = sum([p['w'] for p in processes])

def generate(known_session, known_aoi, aoi, luma, classes):
    step = 0

    optical_data = luma.landsat_version
    thermal_data = optical_data.replace('_SR', '_TOA')  # match Landsat pair automatically
    start_date = luma.start_date.strftime('%Y-%m-%d')
    end_date = luma.end_date.strftime('%Y-%m-%d')
    yield forge_process(step, { 'processes': processes })
    
    #region get optical data
    reflectance = Reflectance_Data()
    collection, meta = reflectance.get_optical_data(
        aoi=aoi,
        start_date=start_date,
        end_date=end_date,
        optical_data=optical_data,
        cloud_cover=luma.cloud_cover,
        verbose=False,
        compute_detailed_stats=False
    )
    step = step + 1
    yield forge_process(step, {})
    #endregion get optical data
    
    #region get thermal data
    #Second, use the same parameter as multispectral data and use it to search collection 2 TOA data. Retrive thermal band only
    #Skip thermal bands for Landsat 1-3 MSS (no thermal capability)
    thermal_collection = None
    if optical_data not in ['L1_RAW', 'L2_RAW', 'L3_RAW']:
        thermal_collection, meta = reflectance.get_thermal_bands(
            aoi=aoi,
            start_date=start_date,
            end_date=end_date,
            thermal_data=thermal_data,
            cloud_cover=luma.cloud_cover,
            verbose=False,
            compute_detailed_stats=False
        )
    else:
        print("ℹ️ Catatan: Sensor MSS pada Landsat 1–3 tidak memiliki kanal termal. Hanya kanal multispektral yang akan diproses.")
    step = step + 1
    yield forge_process(step, {})
    #endregion get thermal data
    
    #region check image count
    stats = Reflectance_Stats()
    detailed_stats = stats.get_collection_statistics(collection, compute_stats=True, print_report=True)
    # Safely get total images count with fallback
    total_images = detailed_stats.get('total_images', 0)
    if total_images == 0:
        # Try alternative keys that might contain the count
        total_images = detailed_stats.get('num_images', 0)
        if total_images == 0:
            # Fallback to collection size
            try:
                total_images = int(collection.size().getInfo())
            except:
                total_images = 0
    
    if total_images <= 0:
        raise AppMessageException('image composite/mosaic for thermal bands not available')
    
    step = step + 1
    yield forge_process(step, {})
    #endregion check image count
    
    #region create image composite
    #Create and image composite/mosaic for thermal bands (if available).
    #Replace the streamlit based composite creation, with backend based process
    image_processor = final_Image()
    if thermal_collection is not None:
        thermal_median = thermal_collection.median().clip(aoi)
        #Create multispectral composite using median via final_Image
        composite = image_processor.get_temporal_composite(collection, aoi, reducer='median', verbose=False)
        #Stack thermal band and ensure float type
        composite = composite.addBands(thermal_median).toFloat()
    else:
        #For Landsat 1-3 MSS: no thermal bands available — use temporal composite
        composite = image_processor.get_temporal_composite(collection, aoi, reducer='median', verbose=False).toFloat()
    
    image = composite
    step = step + 1
    yield forge_process(step, {})
    #endregion create image composite

    #region get training data
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
    step = step + 1
    yield forge_process(step, {})
    #endregion get training data
    
    #region stratified split training data
    roi_ee = converter.convert_roi_gdf(train_gdf)
    class_property = 'class_id'
    pixel_size = 30
    split_ratio = 0.7

    fe = FeatureExtraction()
    train_data_split, testing_data_split = fe.stratified_split(
        roi=roi_ee,
        image=image,
        class_prop=class_property,
        pixel_size=pixel_size,
        train_ratio=split_ratio,
    )
    step = step + 1
    yield forge_process(step, {})
    #endregion stratified split training data

    #region classification
    ntrees = 150
    v_split = None
    min_leaf = 1
    use_auto_vsplit = True

    lulc = Generate_LULC()
    classification_result, trained_model = lulc.hard_classification(
        training_data=train_data_split,
        class_property=class_property,
        image=image,
        ntrees=ntrees,
        v_split=v_split,
        min_leaf=min_leaf,
        return_model=True
    )
    step = step + 1
    yield forge_process(step, {})
    #endregion classification
    
    #region visualization
    unique_df = train_gdf[['class_id', 'class_color']].drop_duplicates('class_id').sort_values('class_id')
    vis_params = {
        'min': int(unique_df['class_id'].min()),
        'max': int(unique_df['class_id'].max()),
        'palette': unique_df['class_color'].tolist()
    }
    Map = geemap.Map()
    Map.centerObject(aoi, 8)
    Map.addLayer(classification_result, vis_params, 'Land Cover Classification')
    layers = []
    for m in Map.ee_layer_dict.keys():
        d = Map.ee_layer_dict[m]
        layers.append({ 'name': m, 'url': d['ee_layer'].url })
    step = step + 1
    yield forge_process(step, { 'layers': layers })
    #endregion visualization

    #region calculate lulc composition
    area_image = ee.Image.pixelArea().addBands(
        classification_result.select('classification')
    )
    areas = area_image.reduceRegion(
        reducer=ee.Reducer.sum().group(
            groupField=1,
            groupName='class_id'
        ),
        geometry=aoi,
        scale=30,
        maxPixels=1e13
    )
    groups = areas.get('groups').getInfo()  # small grouped result only
    area_dict = {g['class_id']: g['sum'] for g in groups}
    total_area = sum(area_dict.values())
    lulc_composition = []
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
    step = step + 1
    yield forge_process(step, { 'lulc_composition': lulc_composition })
    #endregion get lulc composition

    #region feature importance
    importance_df = lulc.get_feature_importance(
        trained_model,
        training_data=train_data_split,
        class_property=class_property
    )
    step = step + 1
    yield forge_process(step, { 'feature_importance': importance_df.to_dict('records') })
    #endregion feature importance

    #region model quality
    model_quality = lulc.evaluate_model(
        trained_model=trained_model,
        test_data=testing_data_split,
        class_property=class_property
    )
    step = step + 1
    yield forge_process(step, {
        'model_quality': {
            'overall_accuracy': model_quality.get('overall_accuracy', 0) * 100,
            'kappa': model_quality.get('kappa', 0),
            'average_f1_score': sum(model_quality.get('f1_scores', [])) / len(model_quality.get('f1_scores', [])),
            'gmean_score': model_quality.get('overall_gmean', 0)
        }
    })
    #endregion model quality

    print('classification result: {}'.format(classification_result))
    print('importance df: {}'.format(importance_df))
    print('model quality: {}'.format(model_quality))
    print('layers: {}'.format(layers))
    print(type(classification_result))
    print(type(classification_result))
    print(type(classification_result))
    print(type(classification_result))
    print(type(classification_result))
    print('Band names:', classification_result.bandNames().getInfo())

    #region export image
    export_image = classification_result.toInt()
    download_url = export_image.getDownloadURL({
        "name": 'LULC_{sensor}_{start_date}_{end_date}'.format(sensor=optical_data, start_date=start_date, end_date=end_date),
        "crs": 'EPSG:4326', # default
        "scale": 30, # default
        "region": aoi,
        "fileFormat": "GEO_TIFF",
        "formatOptions": {"cloudOptimized": True, "noData": 0}
    })
    step = step + 1
    yield forge_process(step, { 'download_url': download_url })
    #endregion export image

    # yield pack({
    #     'layers': layers,
    #     'importance': importance_df.to_dict('records'),
    #     'lulc_composition': lulc_composition,
    #     'download_url': download_url,
    #     'model_quality': {
    #         'overall_accuracy': model_quality.get('overall_accuracy', 0) * 100,
    #         'kappa': model_quality.get('kappa', 0),
    #         'average_f1_score': sum(model_quality.get('f1_scores', [])) / len(model_quality.get('f1_scores', [])),
    #         'gmean_score': model_quality.get('overall_gmean', 0)
    #     }
    # })