import ee

from flask import current_app

from luma_ge.data_acquisition import Reflectance_Data, Reflectance_Stats, final_Image

SENTINEL2_SENSORS = ('S2_SR',)
# Sensors without a thermal band: Landsat 1-3 MSS and Sentinel-2.
NO_THERMAL_SENSORS = ('L1_RAW', 'L2_RAW', 'L3_RAW') + SENTINEL2_SENSORS


def is_sentinel2(optical_data):
    return optical_data in SENTINEL2_SENSORS


def cloud_property(optical_data):
    """Scene-level cloud cover property of the sensor's collection."""
    return 'CLOUDY_PIXEL_PERCENTAGE' if is_sentinel2(optical_data) else 'CLOUD_COVER_LAND'


def get_optical_collection(reflectance, aoi, start_date, end_date, optical_data, cloud_cover):
    """
    Cloud-masked collection with the standard band names (BLUE, GREEN, RED,
    NIR, SWIR1, SWIR2, ...) scaled to reflectance (0-1), for any sensor.
    """
    if is_sentinel2(optical_data):
        # Level-1C TOA before 2017-03-28 (no Level-2A SR in Earth Engine yet), SR after.
        collection, meta = reflectance.get_s2_optical_data(
            aoi=aoi,
            start_date=start_date,
            end_date=end_date,
            cloud_cover=cloud_cover,
            verbose=False,
            compute_detailed_stats=False
        )
        # get_s2_optical_data keeps the raw DN (0-10000); scale like Landsat.
        return collection.map(reflectance.apply_s2_scale_factors), meta

    return reflectance.get_optical_data(
        aoi=aoi,
        start_date=start_date,
        end_date=end_date,
        optical_data=optical_data,
        cloud_cover=cloud_cover,
        verbose=False,
        compute_detailed_stats=False
    )


def get_thermal_collection(reflectance, aoi, start_date, end_date, optical_data, cloud_cover):
    """Thermal (TOA) collection for the sensor; None when it has no thermal band."""
    if optical_data in NO_THERMAL_SENSORS:
        return None
    thermal_collection, _meta = reflectance.get_thermal_bands(
        aoi=aoi,
        start_date=start_date,
        end_date=end_date,
        thermal_data=optical_data.replace('_SR', '_TOA'),
        cloud_cover=cloud_cover,
        verbose=False,
        compute_detailed_stats=False
    )
    return thermal_collection


def median_composite(collection, aoi):
    result = final_Image().get_temporal_composite(collection, aoi, reducer='median', verbose=False)
    # luma_ge returns {'image', 'metadata', 'coverage'} since its Sentinel-2
    # refactor; older builds return the image itself.
    return result['image'] if isinstance(result, dict) else result


def build_composite(aoi, start_date, end_date, landsat_version='L8_SR', cloud_cover=30, return_collection=False):

    optical_data = landsat_version

    reflectance = Reflectance_Data()
    collection, _meta = get_optical_collection(reflectance, aoi, start_date, end_date, optical_data, cloud_cover)
    thermal_collection = get_thermal_collection(reflectance, aoi, start_date, end_date, optical_data, cloud_cover)

    try:
        stats = Reflectance_Stats()
        detailed_stats = stats.get_collection_statistics(collection, compute_stats=True, print_report=False)
        total_images = detailed_stats.get('total_images', 0) or detailed_stats.get('num_images', 0)
        if not total_images:
            try:
                total_images = int(collection.size().getInfo())
            except Exception:
                total_images = 0
        if total_images <= 0:
            return (None, None) if return_collection else None
    except Exception as e:
        current_app.logger.error('build_composite: image count check failed: {}'.format(e))
        return (None, None) if return_collection else None

    if thermal_collection is not None:
        thermal_median = thermal_collection.median().clip(aoi)
        composite = median_composite(collection, aoi)
        composite = composite.addBands(thermal_median).toFloat()
    else:
        composite = median_composite(collection, aoi).toFloat()

    if return_collection:
        return composite, collection
    return composite