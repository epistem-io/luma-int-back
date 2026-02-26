import geopandas as gpd
import geemap

from application import db
from application.logic.geos.aoi import converter
from application.utils.common import AppMessageException

from luma_ge.data_acquisition import Reflectance_Data, Reflectance_Stats, final_Image
from luma_ge.classification import FeatureExtraction, Generate_LULC

def generate(known_session, known_aoi, aoi, luma, classes, train_data):

    optical_data = luma.landsat_version
    thermal_data = optical_data.replace('_SR', '_TOA')  # match Landsat pair automatically

    # raise AppMessageException('{} - {}'.format(luma.start_date.strftime('%Y-%m-%d'), luma.end_date.strftime('%Y-%m-%d')))
    
    reflectance = Reflectance_Data()
    collection, meta = reflectance.get_optical_data(
        aoi=aoi,
        start_date=luma.start_date.strftime('%Y-%m-%d'),
        end_date=luma.end_date.strftime('%Y-%m-%d'),
        optical_data=optical_data,
        cloud_cover=luma.cloud_cover,
        verbose=False,
        compute_detailed_stats=False
    )
    #Second, use the same parameter as multispectral data and use it to search collection 2 TOA data. Retrive thermal band only
    #Skip thermal bands for Landsat 1-3 MSS (no thermal capability)
    thermal_collection = None
    if optical_data not in ['L1_RAW', 'L2_RAW', 'L3_RAW']:
        thermal_collection, meta = reflectance.get_thermal_bands(
            aoi=aoi,
            start_date=luma.start_date.strftime('%Y-%m-%d'),
            end_date=luma.end_date.strftime('%Y-%m-%d'),
            thermal_data=thermal_data,
            cloud_cover=luma.cloud_cover,
            verbose=False,
            compute_detailed_stats=False
        )
    else:
        print("ℹ️ Catatan: Sensor MSS pada Landsat 1–3 tidak memiliki kanal termal. Hanya kanal multispektral yang akan diproses.")
    
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

    importance_df = lulc.get_feature_importance(
        trained_model,
        training_data=train_data_split,
        class_property=class_property
    )

    model_quality = lulc.evaluate_model(
        trained_model=trained_model,
        test_data=testing_data_split,
        class_property=class_property
    )

    unique_classes = {}
    for idx, d in train_gdf.iterrows():
        if not unique_classes.get(d['class_id']):
            unique_classes[d['class_id']] = d['class_color']
    
    vis_params = {
        'min': min(unique_classes.keys()),
        'max': max(unique_classes.keys()),
        'palette': [c for c in unique_classes.values()]
    }

    
    Map = geemap.Map()
    Map.centerObject(aoi, 8)
    Map.addLayer(classification_result, vis_params, 'Land Cover Classification')

    layers = []
    for m in Map.ee_layer_dict.keys():
        d = Map.ee_layer_dict[m]
        layers.append({ 'name': m, 'url': d['ee_layer'].url })

    print('classification result: {}'.format(classification_result))
    print('importance df: {}'.format(importance_df))
    print('model quality: {}'.format(model_quality))
    print('layers: {}'.format(layers))

    return {
        'layers': layers,
        'importance': importance_df.to_dict('records'),
        'model_quality': {
            'overall_accuracy': model_quality.get('overall_accuracy', 0) * 100,
            'kappa': model_quality.get('kappa', 0),
            'average_f1_score': sum(model_quality.get('f1_scores', [])) / len(model_quality.get('f1_scores', [])),
            'gmean_score': model_quality.get('overall_gmean', 0)
        }
    }