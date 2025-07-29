import numpy as np
import matplotlib.pyplot as plt
import pandas as pd

import ee
import geemap

from application.utils.gee import get_aoi_from_gaul, get_landsat_composite, add_spectral_indices, split_training_validation, sample_composite

class TestEarthengineLogic:

    @staticmethod
    def test_ee_v2():
        # --- Area of Interest (AOI) ---
        # Set the country and province for the AOI using GAUL admin boundaries
        COUNTRY = "Indonesia"
        PROVINCE = "Sumatera Selatan"

        # --- Time Period ---
        # Set the analysis year and date range
        START_DATE = '2018-01-01'
        END_DATE = '2018-12-31'

        # --- Landsat Settings ---
        # Choose Landsat version: 'LC08' for Landsat 8, 'LC09' for Landsat 9
        LANDSAT_VERSION = 'LC08'
        CLOUD_COVER = 50  # Maximum cloud cover percentage

        # --- Bands to Use ---
        # List of bands and indices to use for classification
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

        aoi = get_aoi_from_gaul(country=COUNTRY, province=PROVINCE)
        # Visualise the AOI
        Map = geemap.Map() 
        Map.addLayer(aoi, 
                    {'color': 'red', 'fillColor': '00000000'}, 
                    'Area of Interest (AOI)',)
        # Visualize AOI
        Map.centerObject(aoi, 8)

        landsat_composite = get_landsat_composite(
            aoi=aoi,
            start_date=START_DATE,
            end_date=END_DATE,
            landsat_version=LANDSAT_VERSION,
            cloud_cover=CLOUD_COVER
        )

        Map.addLayer(landsat_composite, 
                    {'bands': ['SR_B4', 'SR_B3', 'SR_B2'], 'min': 0, 'max': 0.3}, 
                    'Composite (RGB)')

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

        # Input selected bands
        training_samples = sample_composite(composite_with_indices, training, BANDS)
        validation_samples = sample_composite(composite_with_indices, validation, BANDS)

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

        # Classify with tileScale for memory optimization
        classified = (composite_with_indices.select(BANDS)
                    .classify(trained)
                    .set('system:time_start', ee.Date(START_DATE).millis()))
        
        validated = validation_samples.classify(trained)
        confusion_matrix = validated.errorMatrix('kelas', 'classification')

        print('=== ACCURACY RESULTS ===')
        print('Overall Accuracy:', confusion_matrix.accuracy().getInfo())
        print('Kappa Coefficient:', confusion_matrix.kappa().getInfo())

        # Add RGB composite layer
        Map.addLayer(
            landsat_composite,
            {'bands': ['SR_B4', 'SR_B3', 'SR_B2'], 'min': 0, 'max': 0.3},
            'RGB Composite'
        )

        # Add classified land cover layer
        Map.addLayer(
            classified.clip(aoi),
            {'min': 1, 'max': 17, 'palette': land_cover_palette},
            'Land Cover Classification'
        )

        # Create legend 
        legend_dict = dict(zip(land_cover_names, land_cover_palette))
        Map.add_legend(
            title="Land Cover Classes",
            legend_dict=legend_dict,
            draggable=True
        )

        layers = []
        for m in Map.ee_layer_dict.keys():
            d = Map.ee_layer_dict[m]
            layers.append({ 'name': m, 'url': d['ee_layer'].url })
        
        return { 'message': 'success', 'layers': layers }


    @staticmethod
    def test_ee():
        admin_l1 = ee.FeatureCollection("FAO/GAUL/2015/level1")
        admin_aoi = admin_l1.filter(ee.Filter.eq('ADM1_NAME', 'Sumatera Selatan'))

        styleParams = {
            'fillColor': 'b5ffb4', 
            'color': '000000',     
            'width': 1.0   
        }

        # admin_aoi_styled = admin_aoi.style(**styleParams) 

        # Map = geemap.Map()
        # Map.centerObject(admin_aoi, 8)
        # Map.addLayer(admin_aoi_styled, {}, 'Area of Interest')

        # 1. Define Parameters
        aoi = admin_aoi.geometry() # Get the geometry from the FeatureCollection
        start_date_dry = '2023-06-01'
        end_date_dry = '2023-10-30'
        landsat8_c2_l2_id = 'LANDSAT/LC08/C02/T1_L2' # Landsat 8 Collection 2 SR

        # 2. Cloud Masking Function for Landsat 8 Collection 2 SR
        # Uses the QA_PIXEL band
        def maskL8sr(image):
            # Bits 3 (Cloud) and 4 (Cloud Shadow) are relevant.
            # Bit 1 (Dilated Cloud) can also be included for more aggressive masking.
            cloud_shadow_bit_mask = (1 << 4)
            clouds_bit_mask = (1 << 3)
            dilated_cloud_bit_mask = (1 << 1) # Optional: include dilated cloud

            # Get the pixel QA band.
            qa = image.select('QA_PIXEL')

            # Both flags should be set to zero, indicating clear conditions.
            # Use .eq(0) to check if the bit is 0.
            mask = qa.bitwiseAnd(cloud_shadow_bit_mask).eq(0) \
                    .And(qa.bitwiseAnd(clouds_bit_mask).eq(0))
                    # .And(qa.bitwiseAnd(dilated_cloud_bit_mask).eq(0)) # Optional

            # Select surface reflectance bands and apply the mask
            # Also scale the reflectance values (0-65535 to 0-1, typical range 0-0.6)
            # Scaling factor and offset are from the dataset documentation
            optical_bands = image.select('SR_B.').multiply(0.0000275).add(-0.2)
            # thermal_bands = image.select('ST_B.*').multiply(0.00341802).add(149.0) # Optional: scale thermal bands too

            # Return the scaled optical bands with the mask applied
            return optical_bands.updateMask(mask).copyProperties(image, ["system:time_start"])

        # 3. Filter the Landsat 8 Collection
        l8_collection = ee.ImageCollection(landsat8_c2_l2_id) \
            .filterBounds(aoi) \
            .filterDate(start_date_dry, end_date_dry)

        # 4. Apply the Cloud Masking function
        l8_masked = l8_collection.map(maskL8sr)

        # 5. Create the Median Composite
        # The median reducer will find the median value for each pixel over the time series
        l8_composite = l8_masked.median()

        # 6. Clip the Composite to the exact AOI geometry
        # l8_composite_clipped = l8_composite.clip(admin_aoi) # Clip using the FeatureCollection directly
        l8_composite_clipped = l8_composite # Clip using the FeatureCollection directly

        print("Landsat 8 Dry Season Composite Generated and Clipped.")

        # 7. Define Visualization Parameters (True Color)
        # Using the scaled reflectance values (approx 0-0.3 is a common range for visualization)
        # visParams_L8_TrueColor = {
        #     'bands': ['SR_B4', 'SR_B3', 'SR_B2'], # Red, Green, Blue
        #     'min': 0.0,
        #     'max': 0.3, # Adjust this range if image is too dark/bright
        #     'gamma': 1.4
        # }

        # 8. Add to Map (Optional - if using geemap)
        # Make sure 'Map' is your geemap.Map object variable name
        # Map.centerObject(admin_aoi, 8) # Center the map
        # Map.addLayer(
        #     l8_composite_clipped,
        #     visParams_L8_TrueColor,
        #     'Landsat 8 SR Composite 2024 Dry (Clipped)'
        # )

        print('Composite Image Info:', l8_composite_clipped.getInfo())
        print('Composite Image Serialize:', l8_composite_clipped.serialize())

        # Define the asset ID where the exported image will be stored in Google Earth Engine Assets
        assetId = 'projects/staging-scene-428902/assets/epistem-14jun' ## epistem = file name

        # print(aoi)
        # print(dir(aoi))
        # print(type(aoi))
        # print(aoi.length())
        # # print(aoi.getInfo())
        # print(aoi.distance())
        # print(l8_composite_clipped)
        ## Export the composite image to Google Earth Engine Assets
        geemap.ee_export_image_to_asset(
            l8_composite_clipped, 
            description='l8_composite_2', 
            assetId=assetId, 
            region=aoi, 
            scale=30, 
            maxPixels = 1e9
        )
        # geemap.ee_export_image_to_cloud_storage(
        #     image=l8_composite_clipped,
        #     description='l8_composite_2',
        #     bucket='staging-bucket-be',           
        #     fileNamePrefix='l8_composite_2',     
        #     region=aoi,
        #     scale=30,
        #     maxPixels=1e9
        # )
        # geemap.download_ee_image(
        #     image=l8_composite_clipped,
        #     filename='l8_composite_2.tif',
        #     region=aoi,
        #     scale=30,
        #     crs='EPSG:4326',  # You can adjust CRS if needed
        #     # file_per_band=False  # Set to True if you want separate files per band
        # )

        return { 'message': 'success' }