import ee
import geemap

from .gee_utils import get_aoi_from_gaul, get_landsat_composite, add_spectral_indices, split_training_validation, sample_composite, get_aoi_from_gaul_regency, get_training_points_for_aoi

BANDS = [
    'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7',  # Surface reflectance bands
    'NDVI', 'NBR', 'NDWI', 'EVI2'                          # Spectral indices
]

# --- Reference Data ---
# Path to the ground truth points FeatureCollection (should contain 17 LULC classes)
# TRAINING_POINTS_ASSET = 'projects/ee-rg2icraf/assets/Sumsel_GT_Restore'
USER_TRAINING_POINTS_ASSET = None
TRAINING_POINTS_ASSET = 'projects/ee-rg2icraf/assets/Indonesia_lulc_Sample'

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

# Training points validation settings
CLASS_PROPERTY = 'kelas'  # Property containing LULC class labels (1-17)
MIN_POINTS_PER_CLASS = 10  # Minimum points per class for quality warnings



def f05_generate_lulc_map(
    aoi:ee.Geometry,
    start_date:str,
    end_date:str,
    landsat_version:str,
    cloud_cover:int,
    training_points_asset:str):

    Map = geemap.Map()
    Map.centerObject(aoi, 8)

    # if test_timeout:
    # aoi = get_aoi_from_gaul(country='Indonesia', province='Sumatera Selatan')

    print('------------------------start f05_generate_lulc_map')
    f05_01_a_load_area_of_interest(Map, aoi)
    print('------------------------passed f05_01_a')
    landsat_composite = f05_01_b_generate_composite(Map, aoi, start_date, end_date, landsat_version, cloud_cover)
    print('------------------------passed f05_01_b')
    composite_with_indices = f05_02_a_calculate_spectral_indicies(Map, aoi, landsat_composite)
    print('------------------------passed f05_02_a')
    training, validation = f05_03_a_prepare_training_and_validation_data(Map, aoi, training_points_asset)
    print('------------------------passed f05_03_a')
    training_samples, validation_samples = f05_04_a_feature_extraction_optimized_sampling(Map, composite_with_indices, training, validation)
    print('------------------------passed f05_04_a')
    results = f05_05_model_training_n_validation(Map, aoi, start_date, composite_with_indices, training_samples, validation_samples)
    print('------------------------passed f05_05_model_training_n_validation')

    layers = []
    for m in Map.ee_layer_dict.keys():
        d = Map.ee_layer_dict[m]
        layers.append({ 'name': m, 'url': d['ee_layer'].url })
    
    
    legend_dict = {
        'Area of Interest (AOI)': { 'Area of Interest (AOI)': '#FF0000' },
        'Composite (RGB)': { 'Composite (RGB)': '#FFFFFF' },
        'NDVI': { 'NDVI': ['#d73027', '#f46d43', '#fdae61', '#fee08b', '#d9ef8b', '#a6d96a', '#66bd63', '#1a9641'] },
        'NDWI': { 'NDWI': ['#8B4513', '#DAA520', '#FFFF00', '#ADFF2F', '#00FF00', '#00FFFF', '#0000FF', '#000080'] },
        'Training Points': { 'Training Points': '#0000FF' },
        'Validation Points': { 'Validation Points': '#FFA500' },
        'Land Cover Classification (2018)': [{n: land_cover_palette[i]} for i, n in enumerate(land_cover_names)],
    }

    return { 'message': 'success', 'layers': layers, 'results': results, 'legends': legend_dict }

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

def f05_03_a_prepare_training_and_validation_data(Map:geemap.Map, aoi:ee.Geometry, training_points_asset:str):
    # Load and validate training points for BANYUASIN using the new flexible system
    print(f"\n=== LOADING TRAINING POINTS ===")
    training_points = get_training_points_for_aoi(
        aoi_geometry=aoi,
        user_training_points_asset=USER_TRAINING_POINTS_ASSET,
        backup_training_points_asset=training_points_asset,
        class_property=CLASS_PROPERTY,
        min_points_per_class=MIN_POINTS_PER_CLASS
    )

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
    # Sample satellite data at training and validation point locations for BANYUASIN
    print(f"Sampling satellite data")
    training_samples = sample_composite(composite_with_indices, training, BANDS, class_property=CLASS_PROPERTY)
    validation_samples = sample_composite(composite_with_indices, validation, BANDS, class_property=CLASS_PROPERTY)
    
    return training_samples, validation_samples

def f05_05_model_training_n_validation(Map:geemap.Map, aoi:ee.Geometry, start_date:str, composite_with_indices:ee.Image, training_samples:ee.FeatureCollection, validation_samples:ee.FeatureCollection):
    # F05.05.A Model Training using RandomForest
    # Configure Random Forest classifier optimized for BANYUASIN's diverse land cover
    print(f"Training Random Forest classifier")
    classifier = ee.Classifier.smileRandomForest(
        # Optimized hyper-parameters for BANYUASIN's 17 LULC classes
        numberOfTrees=100,  # Balanced performance vs speed
        variablesPerSplit=3,  # Good for 10 input features
        minLeafPopulation=2,  # Prevent overfitting
        bagFraction=0.7,  # Robust sampling
        seed=42  # Reproducible results
    )

    # Train the classifier using BANYUASIN training samples
    trained = classifier.train(
        features=training_samples,
        classProperty=CLASS_PROPERTY,
        inputProperties=BANDS
    )
    print(f"Classifier training complete.")
    
    # F05.05.B Classification
    # Classify with tileScale for memory optimization
    print(f"Applying classification")
    classified = (composite_with_indices.select(BANDS)
                .classify(trained)
                .set('system:time_start', ee.Date(start_date).millis()))
    print(f"Classification complete")
    
    # F05.05.C Validation
    print(f"\n=== ACCURACY ASSESSMENT ===")
    validated = validation_samples.classify(trained)
    confusion_matrix = validated.errorMatrix(CLASS_PROPERTY, 'classification')

    print('=== ACCURACY RESULTS ===')
    overall_accuracy = confusion_matrix.accuracy().getInfo()
    kappa_coefficient = confusion_matrix.kappa().getInfo()
    print('Overall Accuracy:', overall_accuracy)
    print('Kappa Coefficient:', kappa_coefficient)

    if overall_accuracy >= 0.7:
        accuracy_assessment = 'akurasi yang baik tercapai'
    elif overall_accuracy >= 0.6:
        accuracy_assessment = 'akurasi sedang - dapat diterima untuk pembuktian konsep'
    else:
        accuracy_assessment = 'akurasi rendah - pertimbangkan data pelatihan tambahan atau perubahan parameter'

    # F05.05.D Visualization
    # Add classified land cover layer
    Map.addLayer(
        classified.clip(aoi),
        {'min': 1, 'max': 17, 'palette': land_cover_palette},
        'Land Cover Classification (2018)'
    )

    return {
        'overall_accuracy': overall_accuracy,
        'kappa_coefficient': kappa_coefficient,
        'accuracy_assessment': accuracy_assessment
    }