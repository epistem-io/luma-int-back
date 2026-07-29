import geopandas as gpd

from application import db
from application.logic.geos.aoi import converter
from application.logic.luma.composite import build_composite
from application.logic.luma.training_data import get_current_class_scheme, find_lulc_column
from application.utils.common import AppMessageException, ErrorCodeEnum

from luma_ge.accuracy import thematic_accuracy
from luma_ge.classification import FeatureExtraction, Generate_LULC
from luma_ge.predictor import PredictorCalculation

SPLIT_RATIO = 0.7
CLASS_PROPERTY = 'class_id'


def parse_validation_file(known_session, filepath):
    """
    Read a validation shapefile and map its class column onto the session's
    LULC scheme, using the same column matching rules as training data.
    Returns a GeoDataFrame with a numeric `class_id` column (EPSG:4326).
    """
    gdf = gpd.read_file(filepath)

    reference_set, reference_dict_id, reference_dict_name = get_current_class_scheme(known_session)

    target_field, confidence = find_lulc_column(gdf, reference_set)
    if confidence < 1.0:
        raise AppMessageException('not all of the class is match with the reference class', error=ErrorCodeEnum.ERR_VALIDATION)

    reference_dict_type = 'id'
    try:
        if reference_dict_name.get(str(gdf[target_field].iloc[0]).lower()):
            reference_dict_type = 'name'
    except Exception:
        pass

    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    if reference_dict_type == 'name':
        gdf[CLASS_PROPERTY] = [
            reference_dict_name[str(v).strip().lower()]['id'] for v in gdf[target_field]
        ]
    else:
        gdf[CLASS_PROPERTY] = [int(v) for v in gdf[target_field]]

    return gdf[[CLASS_PROPERTY, 'geometry']]


def _classify(known_session, aoi, luma):
    """
    Rebuild the classified LULC map for the session (composite + optional
    predictors + random forest), mirroring the classification part of
    lulc_map.generate. Returns an ee.Image with a 'classification' band.
    """
    session_id = known_session.id

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
        params={'session_id': session_id}
    )
    if train_gdf.empty:
        raise AppMessageException('training data (step-3) not found', error=ErrorCodeEnum.ERR_VALIDATION)

    image, collection = build_composite(
        aoi=aoi,
        start_date=luma.start_date.strftime('%Y-%m-%d'),
        end_date=luma.end_date.strftime('%Y-%m-%d'),
        landsat_version=luma.landsat_version,
        cloud_cover=luma.cloud_cover,
        return_collection=True,
    )
    if image is None:
        raise AppMessageException('no imagery available for the selected period and area', error=ErrorCodeEnum.ERR_VALIDATION)

    if luma.use_predictor:
        predictor_service = PredictorCalculation()
        result = predictor_service.compute_predictors(
            composite=image,
            aoi=aoi,
            predictor_config=luma.predictor_config,
            collection=collection,
        )
        image = result['stacked_predictors']

    roi_ee = converter.convert_roi_gdf(train_gdf)

    fe = FeatureExtraction()
    train_data_split, _testing_data_split = fe.stratified_split(
        roi=roi_ee,
        image=image,
        class_prop=CLASS_PROPERTY,
        pixel_size=luma.spatial_resolution,
        train_ratio=SPLIT_RATIO,
    )

    lulc = Generate_LULC()
    classification_result = lulc.hard_classification(
        training_data=train_data_split,
        class_property=CLASS_PROPERTY,
        image=image,
        ntrees=luma.ntrees,
        v_split=None,
        min_leaf=luma.min_leaf,
        return_model=False,
    )

    return classification_result


def assess(known_session, aoi, luma, validation_gdf):
    """
    Run the thematic accuracy assessment of the session's LULC map against
    independent validation points. Returns a plain-JSON-serializable dict.
    """
    lcmap = _classify(known_session, aoi, luma)

    validation_ee = converter.convert_roi_gdf(validation_gdf)

    analyzer = thematic_accuracy()
    success, results = analyzer.run_accuracy_assessment(
        lcmap=lcmap,
        validation_data=validation_ee,
        class_property=CLASS_PROPERTY,
        scale=luma.spatial_resolution,
    )
    if not success:
        raise AppMessageException(results.get('error', 'thematic accuracy assessment failed'))

    # Producer/user/F1 arrays are indexed by class value (0..max class id);
    # map them onto the session's class scheme.
    _reference_set, reference_dict_id, _reference_dict_name = get_current_class_scheme(known_session)

    producer = results['producer_accuracy']
    user = results['user_accuracy']
    f1 = results['f1_scores']

    per_class = []
    for class_id in sorted(reference_dict_id.keys()):
        if class_id >= len(producer):
            continue
        ref = reference_dict_id[class_id]
        per_class.append({
            'class_id': int(class_id),
            'class_name': ref['name'],
            'class_color': ref['color'],
            'producer_accuracy': float(producer[class_id]),
            'user_accuracy': float(user[class_id]),
            'f1_score': float(f1[class_id]),
        })

    ci = results.get('overall_accuracy_ci') or (0.0, 0.0)

    # Per-point results for the error map / raw data download: sample the
    # classified map at each validation point, keeping geometries.
    points = []
    try:
        validation_sample = lcmap.select('classification').sampleRegions(
            collection=validation_ee,
            properties=[CLASS_PROPERTY],
            scale=luma.spatial_resolution,
            geometries=True,
            tileScale=4,
        )
        for feature in validation_sample.getInfo().get('features', []):
            geometry = feature.get('geometry') or {}
            coordinates = geometry.get('coordinates') or [None, None]
            properties = feature.get('properties') or {}

            actual_id = int(properties.get(CLASS_PROPERTY))
            predicted_id = int(properties.get('classification'))

            points.append({
                'lon': float(coordinates[0]),
                'lat': float(coordinates[1]),
                'actual_class_id': actual_id,
                'actual_class_name': reference_dict_id.get(actual_id, {}).get('name', 'Class {}'.format(actual_id)),
                'predicted_class_id': predicted_id,
                'predicted_class_name': reference_dict_id.get(predicted_id, {}).get('name', 'Class {}'.format(predicted_id)),
                'is_correct': actual_id == predicted_id,
            })
    except Exception as e:
        # The summary metrics are still valid without per-point data.
        from flask import current_app
        current_app.logger.error('thematic accuracy: per-point sampling failed: {}'.format(e))

    return {
        'points': points,
        'overall_accuracy': float(results['overall_accuracy']),
        'overall_accuracy_ci': [float(ci[0]), float(ci[1])],
        'confidence_level': float(results.get('confidence_level', 0.95)),
        'kappa': float(results['kappa']),
        'per_class': per_class,
        'confusion_matrix': [[int(v) for v in row] for row in results['confusion_matrix']],
        'n_total': int(results['n_total']),
        'n_correct': int(results['n_correct']),
        'scale': int(results['scale']),
    }
