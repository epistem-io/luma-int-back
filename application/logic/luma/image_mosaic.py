import ee
import geemap
import pandas as pd

from datetime import datetime

from luma_ge.data_acquisition import Reflectance_Data, Reflectance_Stats, final_Image

from flask import current_app
from application.utils.common import get_date, AppMessageException, ErrorCodeEnum
from application.feature_flags import mosaic_fast_path, mosaic_layers, mosaic_parallel_workers

from concurrent.futures import ThreadPoolExecutor

RAW_SENSORS = ('L1_RAW', 'L2_RAW', 'L3_RAW')

THERMAL_LAYER = 'Composite - Thermal Band'
THERMAL_VIS = { 'min': 286, 'max': 300, 'gamma': 0.4 }

BAND_COMBINATIONS = {
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

def generate(
    session_id: str,
    aoi:ee.Geometry,
    start_date:str,
    end_date:str,
    landsat_version:str = 'L8_SR',
    cloud_cover:int = 30,
    spatial_resolution:int = 30):

    optical_data = landsat_version

    if mosaic_fast_path():
        return _generate_fast(aoi, start_date, end_date, optical_data, cloud_cover)

    # Original path (MOSAIC_FAST_PATH=0), unchanged.
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
    if optical_data not in RAW_SENSORS:
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
        raise _no_images_error(optical_data, start_date, end_date, cloud_cover)

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

    Map = geemap.Map()
    Map.centerObject(aoi, 8)
    Map.addLayer(aoi, {'color': 'red', 'fillColor': '00000000'}, 'Area of Interest (AOI)')
    Map.addLayer(collection, BAND_COMBINATIONS['True Color (RGB)'], 'Landsat Collection')
    if thermal_collection is not None:
        Map.addLayer(thermal_median, THERMAL_VIS, THERMAL_LAYER)
    
    for selected_combination in BAND_COMBINATIONS.keys():
        vis_params = BAND_COMBINATIONS[selected_combination]
        Map.addLayer(composite, vis_params, f'Composite - {selected_combination}')

    layers = []
    for m in Map.ee_layer_dict.keys():
        d = Map.ee_layer_dict[m]
        layers.append({ 'name': m, 'url': d['ee_layer'].url })

    return _build_results(
        layers, optical_data, start_date, end_date,
        scene_ids=detailed_stats.get('Scene_ids', []),
        acquisition_dates=detailed_stats.get('individual_dates', []),
        cloud_covers=detailed_stats.get('cloud_cover', {}).get('values', []),
        download_url=get_download_url(composite, aoi, session_id, optical_data, start_date, end_date, spatial_resolution),
    )


def _generate_fast(aoi, start_date, end_date, optical_data, cloud_cover):
    """
    MOSAIC_FAST_PATH version of generate(): same response, far fewer Earth
    Engine round-trips. The original path makes ~11 sequential calls (7 for
    the collection stats, 1 for the thermal size check, then the map ids);
    here the scene metadata is one request that runs alongside the map ids.
    The download URL is left for GET /luma/image-mosaic/download-url.
    """
    reflectance = Reflectance_Data()
    collection, _ = reflectance.get_optical_data(
        aoi=aoi,
        start_date=start_date,
        end_date=end_date,
        optical_data=optical_data,
        cloud_cover=cloud_cover,
        verbose=False,
        compute_detailed_stats=False
    )
    composite = final_Image().get_temporal_composite(collection, aoi, reducer='median', verbose=False).toFloat()

    wanted = set(mosaic_layers())
    candidates = [
        ('Area of Interest (AOI)', ee.Image().paint(aoi, 1, 2), {'palette': ['red']}),
        ('Landsat Collection', collection, BAND_COMBINATIONS['True Color (RGB)']),
    ]
    # The thermal band only feeds its own layer, which the frontend doesn't
    # show, so it is only built (and size-checked) when MOSAIC_LAYERS asks.
    if THERMAL_LAYER in wanted and optical_data not in RAW_SENSORS:
        thermal_layer = _thermal_layer(reflectance, aoi, start_date, end_date, optical_data, cloud_cover)
        if thermal_layer is not None:
            candidates.append(thermal_layer)
    for selected_combination, vis_params in BAND_COMBINATIONS.items():
        candidates.append((f'Composite - {selected_combination}', composite, vis_params))
    selected = [c for c in candidates if c[0] in wanted]

    scene_info = ee.Dictionary({
        'scene_ids': collection.aggregate_array('system:index'),
        'dates': collection.aggregate_array('system:time_start'),
        'cloud_covers': collection.aggregate_array('CLOUD_COVER_LAND'),
    })

    workers = max(1, min(mosaic_parallel_workers(), len(selected) + 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        info_future = pool.submit(scene_info.getInfo)
        layer_futures = [pool.submit(_get_tile_layer, entry) for entry in selected]

        info = info_future.result()
        if not info['scene_ids']:
            # The map ids of an empty composite fail inside Earth Engine with an
            # opaque error; drop them and report the actionable message instead.
            for future in layer_futures:
                future.cancel()
            raise _no_images_error(optical_data, start_date, end_date, cloud_cover)

        layers = [future.result() for future in layer_futures]

    return _build_results(
        layers, optical_data, start_date, end_date,
        scene_ids=info['scene_ids'],
        # Same conversion as luma_ge Reflectance_Stats.get_collection_statistics().
        acquisition_dates=[datetime.fromtimestamp(d / 1000).strftime('%Y-%m-%d') for d in info['dates']],
        cloud_covers=info['cloud_covers'],
        # None = "not computed yet": the frontend requests it lazily via
        # GET /luma/image-mosaic/download-url when the user clicks download.
        # ("" keeps its old meaning of "tried and failed".)
        download_url=None,
    )


def _thermal_layer(reflectance, aoi, start_date, end_date, optical_data, cloud_cover):
    thermal_collection, _ = reflectance.get_thermal_bands(
        aoi=aoi,
        start_date=start_date,
        end_date=end_date,
        thermal_data=optical_data.replace('_SR', '_TOA'),
        cloud_cover=cloud_cover,
        verbose=False,
        compute_detailed_stats=False
    )
    # Older sensors (Landsat 4/5) can have optical scenes but no matching TOA
    # scenes; an empty thermal collection would break the thermal tile layer.
    try:
        if int(thermal_collection.size().getInfo()) == 0:
            current_app.logger.warning('image mosaic: no thermal (TOA) images for {} {}..{}, skipping thermal band'.format(optical_data, start_date, end_date))
            return None
    except Exception as e:
        current_app.logger.warning('image mosaic: thermal size check failed: {}'.format(e))
        return None
    return (THERMAL_LAYER, thermal_collection.median().clip(aoi), THERMAL_VIS)


def _no_images_error(optical_data, start_date, end_date, cloud_cover):
    # An empty collection would only fail later inside Earth Engine (when the
    # composite tiles are requested) with an opaque
    # "Element.get: Parameter 'object' is required and may not be null".
    # Fail early with an actionable message instead.
    return AppMessageException(
        'No {sensor} images found for the selected area between {start} and {end} '
        'with cloud cover below {cc}%. Try a higher cloud cover threshold, '
        'a different year, or another Landsat sensor.'.format(
            sensor=optical_data, start=start_date, end=end_date, cc=cloud_cover),
        error=ErrorCodeEnum.ERR_VALIDATION,
    )


def _build_results(layers, optical_data, start_date, end_date, scene_ids, acquisition_dates, cloud_covers, download_url):
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

    results['download_url'] = download_url
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


def _get_tile_layer(entry):
    """entry: (name, ee_object, vis_params) -> {name, url}. One getMapId call."""
    name, obj, vis = entry
    map_id = obj.getMapId(vis)
    return { 'name': name, 'url': map_id['tile_fetcher'].url_format }