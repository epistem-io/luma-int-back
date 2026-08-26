import ee
import geemap
import pandas as pd

from luma_ge.data_acquisition import Reflectance_Data, Reflectance_Stats, final_Image

from flask import current_app
from application.utils.common import get_date, AppMessageException, ErrorCodeEnum
from application.feature_flags import mosaic_fast_path, mosaic_layers, mosaic_parallel_workers

from concurrent.futures import ThreadPoolExecutor

def generate(
    session_id: str,
    aoi:ee.Geometry,
    start_date:str,
    end_date:str,
    landsat_version:str = 'L8_SR',
    cloud_cover:int = 30,
    spatial_resolution:int = 30):

    optical_data = landsat_version
    
    reflectance = Reflectance_Data()
    collection, meta = reflectance.get_optical_data(
        aoi=aoi,
        start_date=start_date,
        end_date=end_date,
        optical_data=optical_data,
        cloud_cover=cloud_cover,
        verbose=False,
        compute_detailed_stats=False
    )

    thermal_collection = None
    if optical_data not in ['L1_RAW', 'L2_RAW', 'L3_RAW']:
        thermal_data = optical_data.replace('_SR', '_TOA')
        thermal_collection, meta = reflectance.get_thermal_bands(
            aoi=aoi,
            start_date=start_date,
            end_date=end_date,
            thermal_data=thermal_data,
            cloud_cover=cloud_cover,
            verbose=False,
            compute_detailed_stats=False
        )
    
    stats = Reflectance_Stats()
    detailed_stats = stats.get_collection_statistics(collection, compute_stats=True, print_report=True)

    total_images = detailed_stats.get('total_images', 0)
    if total_images == 0:
        total_images = detailed_stats.get('num_images', 0)
    if total_images == 0:
        try:
            total_images = int(collection.size().getInfo())
        except Exception as e:
            total_images = 0

    if total_images == 0:
        # An empty collection would only fail later inside Earth Engine (when the
        # composite tiles are requested) with an opaque
        # "Element.get: Parameter 'object' is required and may not be null".
        # Fail early with an actionable message instead.
        raise AppMessageException(
            'No {sensor} images found for the selected area between {start} and {end} '
            'with cloud cover below {cc}%. Try a higher cloud cover threshold, '
            'a different year, or another Landsat sensor.'.format(
                sensor=optical_data, start=start_date, end=end_date, cc=cloud_cover),
            error=ErrorCodeEnum.ERR_VALIDATION,
        )

    if thermal_collection is not None:
        # Older sensors (Landsat 4/5) can have optical scenes but no matching TOA
        # scenes; an empty thermal collection would break the thermal tile layer.
        try:
            if int(thermal_collection.size().getInfo()) == 0:
                current_app.logger.warning('image mosaic: no thermal (TOA) images for {} {}..{}, skipping thermal band'.format(optical_data, start_date, end_date))
                thermal_collection = None
        except Exception as e:
            current_app.logger.warning('image mosaic: thermal size check failed: {}'.format(e))

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
    
    band_combinations = {
        "True Color (RGB)": {
            'bands': ['RED', 'GREEN', 'BLUE'],
            'min': 0.0,
            'max': 0.3,
            'gamma': 1.4
        },
        "False Color Infrared (NIR/Red/Green)": {
            'bands': ['NIR', 'RED', 'GREEN'],
            'min': 0,
            'max': 0.4,
            'gamma': 1.1
        },
        "Short-wave Infrared (SWIR2/NIR/RED)": {
            'bands': ['SWIR2', 'NIR', 'RED'],
            'min': 0,
            'max': 0.4,
            'gamma': 1.2
        },
        "Land/Water (NIR/SWIR1/RED)": {
            'bands': ['NIR','SWIR1','RED'],
            'min': 0,
            'max': 0.4,
            'gamma': [0.95, 1.1, 1]
        },
        "Kombinasi saluran bebas": {
            'bands': ['NIR', 'RED', 'GREEN'],  # Default for custom
            'min': 0.0,
            'max': 0.4,
            'gamma': 1.0
        }
    }

    fast_path = mosaic_fast_path()

    if fast_path:
        # Only compute the tile layers the frontend actually renders, and fetch
        # their map ids concurrently. No Map.centerObject() (the frontend fits
        # the view to the AOI itself). Set MOSAIC_FAST_PATH=0 to restore the
        # original geemap-based block below.
        thermal_vis = { 'min': 286, 'max': 300, 'gamma': 0.4 }
        candidates = [
            ('Area of Interest (AOI)', ee.Image().paint(aoi, 1, 2), {'palette': ['red']}),
            ('Landsat Collection', collection, band_combinations['True Color (RGB)']),
        ]
        if thermal_collection is not None:
            candidates.append(('Composite - Thermal Band', thermal_median, thermal_vis))
        for selected_combination, vis_params in band_combinations.items():
            candidates.append((f'Composite - {selected_combination}', composite, vis_params))

        wanted = set(mosaic_layers())
        selected = [c for c in candidates if c[0] in wanted]

        layers = _get_tile_layers(selected, workers=mosaic_parallel_workers())
    else:
        Map = geemap.Map()
        Map.centerObject(aoi, 8)
        Map.addLayer(aoi, {'color': 'red', 'fillColor': '00000000'}, 'Area of Interest (AOI)')
        Map.addLayer(collection, band_combinations['True Color (RGB)'], 'Landsat Collection')
        if thermal_collection is not None:
            thermal_vis = { 'min': 286, 'max': 300, 'gamma': 0.4 }
            Map.addLayer(thermal_median, thermal_vis, "Composite - Thermal Band")
        
        for selected_combination in band_combinations.keys():
            vis_params = band_combinations[selected_combination]
            Map.addLayer(composite, vis_params, f'Composite - {selected_combination}')

        layers = []
        for m in Map.ee_layer_dict.keys():
            d = Map.ee_layer_dict[m]
            layers.append({ 'name': m, 'url': d['ee_layer'].url })
    
    results = {
        'layers': layers,
        'summary': [],
        'statistics': {},
        'metadata': {
            'generated_by': 'LUMA',
            'generation_datetime': get_date().strftime('%Y-%m-%d %H:%M:%S'),
            'sensor': optical_data,
            'start_date': start_date,
            'end_date': end_date,
        }
    }

    # bottom section
    scene_ids = detailed_stats.get('Scene_ids', [])
    acquisition_dates = detailed_stats.get('individual_dates', [])
    cloud_covers = detailed_stats.get('cloud_cover', {}).get('values', [])

    if scene_ids and acquisition_dates:
    #Create a dataframe with all information
        scene_df = pd.DataFrame({
            'scene_id': scene_ids,
            'tanggal_perekaman': acquisition_dates,
            'tutupan_awan': [round(cc, 2) for cc in cloud_covers] if cloud_covers else ['N/A'] * len(scene_ids)
        })
        results['summary'] = scene_df.to_dict(orient="records")
        
        results['statistics'] = {
            'min': min(cloud_covers) if cloud_covers else None,
            'max': max(cloud_covers) if cloud_covers else None,
            'mean': sum(cloud_covers)/len(cloud_covers) if cloud_covers else None
        }
    
    # region export
    if fast_path:
        # None = "not computed yet": the frontend requests it lazily via
        # GET /luma/image-mosaic/download-url when the user clicks download.
        # ("" keeps its old meaning of "tried and failed".)
        results['download_url'] = None
    else:
        results['download_url'] = get_download_url(composite, aoi, session_id, optical_data, start_date, end_date, spatial_resolution)
    
    return results


def get_download_url(composite, aoi, session_id, optical_data, start_date, end_date, spatial_resolution):
    """GeoTIFF download URL for the composite; '' when Earth Engine refuses (e.g. > 50 MB)."""
    band_names = composite.bandNames()
    composite = composite.select(band_names)
    try:
        return composite.getDownloadURL({
            "name": 'LULC_{sensor}_{start_date}_{end_date}_{session_id}_IM'.format(sensor=optical_data, start_date=start_date, end_date=end_date, session_id=session_id),
            "crs": 'EPSG:4326', # default
            "scale": spatial_resolution, # default
            "region": aoi,
            "filePerBand": False,
            "fileFormat": "GEO_TIFF",
            "formatOptions": {"cloudOptimized": True}
        })
    except Exception as e:
        current_app.logger.error('failed to get download url: {}'.format(str(e)))
        return ''


def _get_tile_layers(entries, workers=4):
    """
    entries: list of (name, ee_object, vis_params). Returns [{name, url}] in the
    same order, fetching map ids concurrently (each getMapId is one EE call).
    """
    def one(entry):
        name, obj, vis = entry
        map_id = obj.getMapId(vis)
        return { 'name': name, 'url': map_id['tile_fetcher'].url_format }

    if workers <= 1 or len(entries) <= 1:
        return [one(e) for e in entries]

    with ThreadPoolExecutor(max_workers=min(workers, len(entries))) as pool:
        return list(pool.map(one, entries))