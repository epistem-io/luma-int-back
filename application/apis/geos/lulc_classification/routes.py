# application/apis/geos/lulc_classification/routes.py
from application import db
from application.apis.geos import geos_apis_blueprint
from flask import make_response, request, jsonify, current_app, g as g_var
from flask_login import current_user
from flask_cors import cross_origin

import uuid
import arrow

# models
from application.models.geos import Aoi, Lulc
from application.models.user import Session, GeeAsset
from application.models.master import Settings

# logic
from application.logic.geos import f05_generate_lulc_map as logic
from application.logic.geos import aoi as aoi_logic
from application.logic.geos import gee_utils
from application.logic.user import session as session_logic

# utils
from application.utils.common import AppMessageException, get_date, set_attr, get_default_list_param
from application.utils.common import app_exception_handler, success_handler
from application.utils.common import save_uploaded_file, check_file, get_file_extension, process_zip, remove_tree_file, upload_folder


@geos_apis_blueprint.route('/lulc-classification', methods=['POST'])
@cross_origin()
def geos_lulc_classification():
    g_var.__api_name__ = 'geos_lulc_classification'
    g_var.__api_description__ = 'geos lulc classification'
    
    try:
        if not request.is_json:
            raise AppMessageException('please provide json data')
        
        data = request.get_json()
        session_id = data.get('session_id')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        landsat_version = data.get('landsat_version')
        cloud_cover = data.get('cloud_cover')
        use_own_dataset = data.get('use_own_dataset')

        if not start_date:
            raise AppMessageException('please input: start date, format: yyyy-mm-dd')
        if not end_date:
            raise AppMessageException('please input: end date, format: yyyy-mm-dd')
        if not landsat_version:
            raise AppMessageException('please input: landsat version')
        if not cloud_cover:
            raise AppMessageException('please input: cloud cover, format: positive number, max 50')
        
        try:
            start_date = arrow.get(start_date).format('YYYY-MM-DD')
        except Exception as e:
            raise AppMessageException('invalid input: start date, format: yyyy-mm-dd')
        
        try:
            end_date = arrow.get(end_date).format('YYYY-MM-DD')
        except Exception as e:
            raise AppMessageException('invalid input: end date, format: yyyy-mm-dd')
        
        try:
            cloud_cover = int(cloud_cover)
        except Exception as e:
            raise AppMessageException('invalid input: cloud cover, format: positive number, max 50')
        
        if cloud_cover < 0 or cloud_cover > 50:
            raise AppMessageException('invalid input: cloud cover, format: positive number, max 50')

        known_aoi = Aoi.query.filter_by(session_id=session_id).first()
        if not known_aoi:
            raise AppMessageException('aoi not found')

        aoi = aoi_logic.wkb_to_ee_geometry(str(known_aoi.geom))

        training_points_asset = Settings.get_settings('TRAINING_POINTS_ASSET')

        if use_own_dataset:
            known_gee_asset = GeeAsset.query.filter_by(session_id=session_id).order_by(GeeAsset.id.desc()).first()
            if known_gee_asset:
                training_points_asset = known_gee_asset.asset_id
            else:
                raise AppMessageException('own dataset not found')

        results = logic.f05_generate_lulc_map(
            aoi=aoi,
            start_date=start_date,
            end_date=end_date,
            landsat_version=landsat_version,
            cloud_cover=cloud_cover,
            training_points_asset=training_points_asset
        )

        known_lulc = Lulc()
        known_lulc.session_id = session_id
        known_lulc.start_date = start_date
        known_lulc.end_date = end_date
        known_lulc.landsat_version = landsat_version
        known_lulc.cloud_cover = cloud_cover
        known_lulc.training_asset_id = training_points_asset

        db.session.add(known_lulc)
        db.session.commit()

        return make_response(jsonify(success_handler(results)), 200)
    except AppMessageException as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 400) # send bad request
    except Exception as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 500) # send internal error


@geos_apis_blueprint.route('/lulc-classification/upload-training-dataset', methods=['POST'])
@cross_origin()
def geos_lulc_classification_upload_training_dataset():
    g_var.__api_name__ = 'geos_lulc_classification_upload_training_dataset'
    g_var.__api_description__ = 'geos lulc classification upload training dataset'
    
    try:
        data = request.form

        session_id = data.get('session_id')
        file = request.files.get('file')

        extension = check_file(file, {'csv', 'shp', 'zip'})

        known_session = session_logic.init_session(session_id)

        filepath = save_uploaded_file(session_id, file)

        # if extension == 'zip':
        #     filepath = process_zip(filepath, session_id, get_extension='shp')
        #     extension = 'shp'
        
        results = gee_utils.import_file_to_ee('gs://{}/{}'.format(current_app.config.get('GCS_BUCKET_NAME'), filepath), extension=extension, asset_id=known_session.id)
        if results['task_state'] != 'COMPLETED':
            raise AppMessageException('failed to import training dataset.')

        remove_tree_file(upload_folder, known_session.id)

        known_gee_asset = GeeAsset.query.filter_by(session_id=known_session.id).first()
        if not known_gee_asset:
            known_gee_asset = GeeAsset()
            known_gee_asset.session_id = known_session.id
            known_gee_asset.asset_id = results['asset_id']
            db.session.add(known_gee_asset)
            db.session.commit()

        return make_response(jsonify(success_handler({ 'message': 'successs', 'session_id': known_session.id })), 200)
    except AppMessageException as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 400) # send bad request
    except Exception as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 500) # send internal error

