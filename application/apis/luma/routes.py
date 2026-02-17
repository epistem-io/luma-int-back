# application/apis/luma/routes.py
from application import db
from application.apis.luma import luma_apis_blueprint
from flask import make_response, request, jsonify, current_app, g as g_var
from flask_login import current_user
from flask_cors import cross_origin

import os
import uuid
import json
import arrow

# models


# logic
from application.logic.geos import aoi as aoi_logic
from application.logic.user import session as session_logic
from application.logic.luma import image_mosaic, lulc_classes, training_data
from application.logic.geos import gee_utils

# utils
from application.utils.common import AppMessageException, ErrorCodeEnum, ErrorStack
from application.utils.common import get_date, set_attr, get_default_list_param
from application.utils.common import app_exception_handler, success_handler
from application.utils.common import check_file, save_uploaded_file, remove_tree_file, upload_folder, process_zip
from application.utils.common import get_json


@luma_apis_blueprint.route('/image-mosaic', methods=['GET'])
@cross_origin()
def generate_image_mosaic():
    g_var.__api_name__ = 'generate_image_mosaic'
    g_var.__api_description__ = 'generate_image_mosaic'
    
    data = request.args
    session_id = data.get('session_id', '')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    landsat_version = data.get('landsat_version', 'L8_SR')
    cloud_cover = data.get('cloud_cover', 30)

    if not start_date:
        raise AppMessageException('please input: start date, format: yyyy-mm-dd', error=ErrorCodeEnum.ERR_VALIDATION)
    if not end_date:
        raise AppMessageException('please input: end date, format: yyyy-mm-dd', error=ErrorCodeEnum.ERR_VALIDATION)
    
    # if not landsat_version:
    #     raise AppMessageException('please input: landsat version')
    # if not cloud_cover:
    #     raise AppMessageException('please input: cloud cover, format: positive number, max 50')
    
    try:
        start_date = arrow.get(start_date).format('YYYY-MM-DD')
    except Exception as e:
        raise AppMessageException('invalid input: start date, format: yyyy-mm-dd', error=ErrorCodeEnum.ERR_VALIDATION)
    
    try:
        end_date = arrow.get(end_date).format('YYYY-MM-DD')
    except Exception as e:
        raise AppMessageException('invalid input: end date, format: yyyy-mm-dd', error=ErrorCodeEnum.ERR_VALIDATION)
    
    if cloud_cover:
        try:
            cloud_cover = int(cloud_cover)
        except Exception as e:
            raise AppMessageException('invalid input: cloud cover, format: positive number, max 50', error=ErrorCodeEnum.ERR_VALIDATION)
        if cloud_cover < 0 or cloud_cover > 50:
            raise AppMessageException('invalid input: cloud cover, format: positive number, max 50', error=ErrorCodeEnum.ERR_VALIDATION)
    
    aoi = aoi_logic.get_ee_aoi(session_id)

    layers = image_mosaic.generate(aoi, start_date, end_date, landsat_version, cloud_cover)

    results = {
        'message': 'success',
        'layers': layers
    }

    return make_response(jsonify(success_handler(results)), 200)


@luma_apis_blueprint.route('/lulc-classes', methods=['POST'])
@cross_origin()
def define_lulc_classes():
    g_var.__api_name__ = 'define_lulc_classes'
    g_var.__api_description__ = 'define_lulc_classes'
    
    if not request.is_json:
        raise AppMessageException('invalid input: request must be json', error=ErrorCodeEnum.ERR_VALIDATION)
    
    data = request.get_json()

    session_id = data.get('session_id', '')
    classes = data.get('classes', [])
    
    known_session = session_logic.get_session(session_id, validate=True)

    lulc_classes.process(known_session, classes, None, None)
    
    results = {
        'message': 'success',
        'data': { }
    }

    return make_response(jsonify(success_handler(results)), 200)


@luma_apis_blueprint.route('/lulc-classes/upload', methods=['POST'])
@cross_origin()
def lulc_classes_upload():
    g_var.__api_name__ = 'lulc_classes_upload'
    g_var.__api_description__ = 'lulc_classes_upload'
    
    data = request.form

    session_id = data.get('session_id', '')
    file = request.files.get('file')

    extension = check_file(file, {'csv', 'xlsx', 'xls'})
    known_session = session_logic.get_session(session_id, validate=True)

    lulc_classes.process(known_session, None, file, extension)
    
    results = {
        'message': 'success',
        'data': { }
    }

    return make_response(jsonify(success_handler(results)), 200)


@luma_apis_blueprint.route('/lulc-classes', methods=['DELETE'])
@cross_origin()
def lulc_classes_delete():
    g_var.__api_name__ = 'lulc_classes_delete'
    g_var.__api_description__ = 'lulc_classes_delete'
    
    session_id = request.args.get('session_id', '')
    known_session = session_logic.get_session(session_id, validate=True)

    lulc_classes.delete(known_session, commit=True)
    
    results = {
        'message': 'success',
    }

    return make_response(jsonify(success_handler(results)), 200)


@luma_apis_blueprint.route('/training-data', methods=['POST'])
@cross_origin()
def training_data_post():
    g_var.__api_name__ = 'training_data_post'
    g_var.__api_description__ = 'training_data_post'
    
    if not request.is_json:
        raise AppMessageException('invalid input: request must be json', error=ErrorCodeEnum.ERR_VALIDATION)
    
    data = request.get_json()
    
    session_id = data.get('session_id', '')
    input_data = data.get('training_data', [])

    known_session = session_logic.get_session(session_id, validate=True)

    dt = training_data.process(known_session, input_data)
    
    results = {
        'message': 'success',
        'training_data': dt
    }

    return make_response(jsonify(success_handler(results)), 200)


@luma_apis_blueprint.route('/training-data/upload', methods=['POST'])
@cross_origin()
def training_data_upload():
    g_var.__api_name__ = 'training_data_upload'
    g_var.__api_description__ = 'training_data_upload'
    
    data = request.form

    session_id = data.get('session_id', '')
    file = request.files.get('file')

    check_file(file, {'zip'})
    known_session = session_logic.get_session(session_id, validate=True)

    filepath = save_uploaded_file(session_id, file, skip_gcs=True)
    filepath = process_zip(filepath, session_id, get_extension='shp', skip_gcs=True)

    aoi = aoi_logic.get_ee_aoi(session_id)
    dt = training_data.process_file(known_session, aoi, filepath)
    
    remove_tree_file(upload_folder, known_session.id)
    
    results = {
        'message': 'success',
        'training_data': dt
    }

    return make_response(jsonify(success_handler(results)), 200)


@luma_apis_blueprint.route('/training-data', methods=['DELETE'])
@cross_origin()
def training_data_delete():
    g_var.__api_name__ = 'training_data_delete'
    g_var.__api_description__ = 'training_data_delete'
    
    session_id = request.args.get('session_id', '')
    known_session = session_logic.get_session(session_id, validate=True)

    training_data.delete(known_session, commit=True)
    
    results = {
        'message': 'success',
    }

    return make_response(jsonify(success_handler(results)), 200)



@luma_apis_blueprint.route('/task-status/<task_id>', methods=['POST'])
@cross_origin()
def task_status_check(task_id):
    g_var.__api_name__ = 'task_status_check'
    g_var.__api_description__ = 'task_status_check'
    
    data = request.args

    session_id = data.get('session_id', '')
    session_logic.get_session(session_id, validate=True)
    
    results = {
        'message': 'success',
        'status': gee_utils.get_task_status(task_id)
    }

    return make_response(jsonify(success_handler(results)), 200)


