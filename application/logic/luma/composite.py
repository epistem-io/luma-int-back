import ee

from flask import current_app

from luma_ge.data_acquisition import Reflectance_Data, Reflectance_Stats, final_Image

def build_composite(aoi, start_date, end_date, landsat_version='L8_SR', cloud_cover=30, return_collection=False):

    optical_data = landsat_version
    
    reflectance = Reflectance_Data()
    collection, _meta = reflectance.get_optical_data(
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
        thermal_collection, _meta = reflectance.get_thermal_bands(
            aoi=aoi,
            start_date=start_date,
            end_date=end_date,
            thermal_data=thermal_data,
            cloud_cover=cloud_cover,
            verbose=False,
            compute_detailed_stats=False
        )
    
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

    image_processor = final_Image()
    if thermal_collection is not None:
        thermal_median = thermal_collection.median().clip(aoi)
        composite = image_processor.get_temporal_composite(collection, aoi, reducer='median', verbose=False)
        composite = composite.addBands(thermal_median).toFloat()
    else:
        composite = image_processor.get_temporal_composite(collection, aoi, reducer='median', verbose=False).toFloat()

    if return_collection:
        return composite, collection
    return composite