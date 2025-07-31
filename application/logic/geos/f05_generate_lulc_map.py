import ee
import geemap

from .gee_utils import get_aoi_from_gaul, get_landsat_composite, add_spectral_indices, split_training_validation, sample_composite

BANDS = [
    'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7',  # Surface reflectance bands
    'NDVI', 'NBR', 'NDWI', 'EVI2'                          # Spectral indices
]

# --- Reference Data ---
# Path to the ground truth points FeatureCollection (should contain 17 LULC classes)
TRAINING_POINTS_ASSET = 'projects/ee-rg2icraf/assets/Sumsel_GT_Restore'


# --- Visualization ---
# Color palette for each LULC class (order must match class names)
land_cover_palette = [
    '#006400',  # Undisturbed dry-land forest
    '#228B22',  # Logged-over dry-land forest
    '#4169E1',  # Undisturbed mangrove
    '#87CEEB',  # Logged-over mangrove
    '#2E8B57',  # Undisturbed swamp forest
    '#8FBC8F',  # Logged-over swamp forest
    '#9ACD32',  # Agroforestry
    '#32CD32',  # Plantation forest
    '#8B4513',  # Rubber monoculture
    '#FF8C00',  # Oil palm monoculture
    '#DAA520',  # Other monoculture
    '#ADFF2F',  # Grass/savanna
    '#90EE90',  # Shrub
    '#FFFF00',  # Cropland
    '#FF0000',  # Settlement
    '#D2B48C',  # Cleared land
    '#0000FF'   # Waterbody
]

land_cover_names = [
    'Undisturbed dry-land forest',
    'Logged-over dry-land forest',
    'Undisturbed mangrove',
    'Logged-over mangrove',
    'Undisturbed swamp forest',
    'Logged-over swamp forest',
    'Agroforestry',
    'Plantation forest',
    'Rubber monoculture',
    'Oil palm monoculture',
    'Other monoculture',
    'Grass/savanna',
    'Shrub',
    'Cropland',
    'Settlement',
    'Cleared land',
    'Waterbody'
]

def f05_generate_lulc_map(
    aoi:ee.Geometry,
    start_date:str,
    end_date:str,
    landsat_version:str,
    cloud_cover:int):

    Map = geemap.Map()
    Map.centerObject(aoi, 8)

    # aoi = get_aoi_from_gaul(country='Indonesia', province='Sumatera Selatan')

    f05_01_a_load_area_of_interest(Map, aoi)
    landsat_composite = f05_01_b_generate_composite(Map, aoi, start_date, end_date, landsat_version, cloud_cover)
    composite_with_indices = f05_02_a_calculate_spectral_indicies(Map, aoi, landsat_composite)
    training, validation = f05_03_a_prepare_training_and_validation_data(Map)
    training_samples, validation_samples = f05_04_a_feature_extraction_optimized_sampling(Map, composite_with_indices, training, validation)
    results = f05_05_model_training_n_validation(Map, aoi, start_date, composite_with_indices, training_samples, validation_samples)

    layers = []
    for m in Map.ee_layer_dict.keys():
        d = Map.ee_layer_dict[m]
        layers.append({ 'name': m, 'url': d['ee_layer'].url })

    return { 'message': 'success', 'layers': layers, 'results': results }

def f05_01_a_load_area_of_interest(Map:geemap.Map, aoi:ee.Geometry):
    Map.addLayer(aoi, 
            {'color': 'red', 'fillColor': '00000000'}, 
            'Area of Interest (AOI)',)

def f05_01_b_generate_composite(Map:geemap.Map, aoi:ee.Geometry, start_date:str, end_date:str, landsat_version:str, cloud_cover:int):
    landsat_composite = get_landsat_composite(
        aoi=aoi,
        start_date=start_date,
        end_date=end_date,
        landsat_version=landsat_version,
        cloud_cover=cloud_cover
    )

    Map.addLayer(landsat_composite, 
            {'bands': ['SR_B4', 'SR_B3', 'SR_B2'], 'min': 0, 'max': 0.3}, 
            'Composite (RGB)')
    
    return landsat_composite

def f05_02_a_calculate_spectral_indicies(Map:geemap.Map, aoi:ee.Geometry, landsat_composite:ee.Image):
    # Input bands for generate NDVI and NDWI
    composite_with_indices = add_spectral_indices(landsat_composite)

    # Select NDVI and NDWI bands from the composite
    ndvi = composite_with_indices.select('NDVI')
    ndwi = composite_with_indices.select('NDWI')

    # Add NDVI layer
    ndvi_palette = ['#d73027', '#f46d43', '#fdae61', '#fee08b', '#d9ef8b', '#a6d96a', '#66bd63', '#1a9641']
    Map.addLayer(ndvi.clip(aoi), 
                {'min': -1, 'max': 1, 'palette': ndvi_palette}, 
                'NDVI')

    # Add NDWI layer
    ndwi_palette = ['#8B4513', '#DAA520', '#FFFF00', '#ADFF2F', '#00FF00', '#00FFFF', '#0000FF', '#000080']
    Map.addLayer(ndwi.clip(aoi), 
                {'min': -1, 'max': 1, 'palette': ndwi_palette}, 
                'NDWI')
    
    return composite_with_indices

def f05_03_a_prepare_training_and_validation_data(Map:geemap.Map):
    training_points = ee.FeatureCollection(TRAINING_POINTS_ASSET)
    # Check training data size
    print('Total training points:', training_points.size().getInfo())

    # Split points into training and validation sets
    training, validation = split_training_validation(training_points, split=0.7, seed=42)


    print('Training points:', training.size().getInfo())
    print('Validation points:', validation.size().getInfo())

    Map.addLayer(training, 
                {'color': 'blue'}, 
                'Training Points')

    Map.addLayer(validation, 
                {'color': 'orange'}, 
                'Validation Points')
    
    return training, validation

def f05_04_a_feature_extraction_optimized_sampling(Map:geemap.Map, composite_with_indices:ee.Image, training:ee.FeatureCollection, validation:ee.FeatureCollection):
    # Input selected bands
    training_samples = sample_composite(composite_with_indices, training, BANDS)
    validation_samples = sample_composite(composite_with_indices, validation, BANDS)
    
    return training_samples, validation_samples

def f05_05_model_training_n_validation(Map:geemap.Map, aoi:ee.Geometry, start_date:str, composite_with_indices:ee.Image, training_samples:ee.FeatureCollection, validation_samples:ee.FeatureCollection):
    # F05.05.A Model Training using RandomForest
    classifier = ee.Classifier.smileRandomForest(
        # Input hyper-parameter
        numberOfTrees=100,  # Reduced from 200
        variablesPerSplit=3,
        minLeafPopulation=2,  # Increased from 1
        bagFraction=0.7,  # Increased from 0.5
        seed=42
    )

    trained = classifier.train(
        features=training_samples,
        classProperty='kelas',
        inputProperties=BANDS
    )
    
    # F05.05.B Classification
    # Classify with tileScale for memory optimization
    classified = (composite_with_indices.select(BANDS)
                .classify(trained)
                .set('system:time_start', ee.Date(start_date).millis()))
    
    # F05.05.C Validation
    validated = validation_samples.classify(trained)
    confusion_matrix = validated.errorMatrix('kelas', 'classification')

    print('=== ACCURACY RESULTS ===')
    overall_accuracy = confusion_matrix.accuracy().getInfo()
    kappa_coefficient = confusion_matrix.kappa().getInfo()
    print('Overall Accuracy:', overall_accuracy)
    print('Kappa Coefficient:', kappa_coefficient)

    # F05.05.D Visualization
    # Add classified land cover layer
    Map.addLayer(
        classified.clip(aoi),
        {'min': 1, 'max': 17, 'palette': land_cover_palette},
        'Land Cover Classification'
    )

    return {
        'overall_accuracy': overall_accuracy,
        'kappa_coefficient': kappa_coefficient
    }