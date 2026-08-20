# application/apis/geos/aoi/routes.py
from application import db
from application.apis.geos import geos_apis_blueprint
from flask import make_response, request, jsonify, current_app, g as g_var
from flask_login import current_user
from flask_cors import cross_origin

import os
import uuid
import json
from werkzeug.utils import secure_filename

# models
from application.models.geos import Aoi
from application.models.user import Session

# logic
from application.logic.geos import aoi as logic
from application.logic.geos import regency as regency_logic
from application.logic.user import session as session_logic

# utils
from application.utils.common import AppMessageException, ErrorCodeEnum, ErrorStack
from application.utils.common import get_date, set_attr, get_default_list_param
from application.utils.common import app_exception_handler, success_handler
from application.utils.common import allowed_file


@geos_apis_blueprint.route('/aoi', methods=['POST'])
@cross_origin()
def geos_aoi():
    g_var.__api_name__ = 'geos_aoi'
    g_var.__api_description__ = 'geos aoi'
    
    if not request.is_json:
        raise AppMessageException('please provide json data', error=ErrorCodeEnum.ERR_VALIDATION)
    
    data = request.get_json()
    geometry = data.get('geometry')
    session_id = data.get('session_id')

    if not geometry:
        raise AppMessageException('please provide geometry', error=ErrorCodeEnum.ERR_VALIDATION)
    
    known_session = session_logic.init_session(session_id)

    known_aoi = logic.aoi(known_session, geometry)

    db.session.commit()

    results = {
        'message': 'success',
        'data': known_aoi.to_json(),
        'geometry': geometry
    }

    return make_response(jsonify(success_handler(results)), 200)


@geos_apis_blueprint.route('/aoi/upload', methods=['POST'])
@cross_origin()
def geos_aoi_upload():
    g_var.__api_name__ = 'geos_aoi_upload'
    g_var.__api_description__ = 'geos aoi upload'
    
    data = request.form

    session_id = data.get('session_id')
    file = request.files.get('file')

    if not file:
        raise AppMessageException('No selected file', error=ErrorCodeEnum.ERR_VALIDATION)
    if not file.filename:
        raise AppMessageException('No selected file name', error=ErrorCodeEnum.ERR_VALIDATION)
    if not allowed_file(file.filename, {'kml', 'kmz', 'zip'}):
        raise AppMessageException('Invalid file format, only ZIP, KML or KMZ files are allowed', error=ErrorCodeEnum.ERR_VALIDATION)
    
    known_session = session_logic.init_session(session_id)

    upload_folder = 'uploaded-file'
    filepath = os.path.join(upload_folder, known_session.id)
    if not os.path.exists(filepath):
        os.makedirs(filepath)
    
    fullpath = os.path.join(filepath, secure_filename(file.filename))
    file.save(fullpath)

    extension = file.filename.rsplit('.', 1)[1].lower()

    if extension == 'zip':
        geom = logic.process_zip_and_get_polygon(fullpath, known_session.id, upload_folder)
    elif extension == 'kml':
        geom = logic.process_kml_and_get_polygon(fullpath, known_session.id, upload_folder)
    elif extension == 'kmz':
        geom = logic.process_kmz_and_get_polygon(fullpath, known_session.id, upload_folder)
    
    geometry = json.loads(geom)
    geometry = geometry["features"][0]["geometry"]
    known_aoi = logic.aoi(known_session, geometry)

    db.session.commit()

    results = {
        'message': 'success',
        'data': known_aoi.to_json(),
        'geometry': geometry
    }

    return make_response(jsonify(success_handler(results)), 200)


@geos_apis_blueprint.route('/aoi/regencies', methods=['GET'])
@cross_origin()
def geos_aoi_regencies():
    """List Indonesian Kabupaten/Kota for the 'Pilih Kabupaten/Kota' AOI option."""
    g_var.__api_name__ = 'geos_aoi_regencies'
    g_var.__api_description__ = 'geos aoi regency list'

    results = {
        'message': 'success',
        'data': regency_logic.list_regencies(),
    }

    return make_response(jsonify(success_handler(results)), 200)


@geos_apis_blueprint.route('/aoi/regency', methods=['POST'])
@cross_origin()
def geos_aoi_regency():
    """Set the session AOI to the polygon of the selected Kabupaten/Kota (by KDPKAB code)."""
    g_var.__api_name__ = 'geos_aoi_regency'
    g_var.__api_description__ = 'geos aoi from regency'

    if not request.is_json:
        raise AppMessageException('please provide json data', error=ErrorCodeEnum.ERR_VALIDATION)

    data = request.get_json()
    code = data.get('code')
    session_id = data.get('session_id')

    if not code:
        raise AppMessageException('please provide regency code', error=ErrorCodeEnum.ERR_VALIDATION)

    geometry, area_m2, regency = regency_logic.get_regency_geojson(code)

    known_session = session_logic.init_session(session_id)

    known_aoi = logic.save_aoi(known_session, geometry, area_m2, regency_code=regency['code'])

    db.session.commit()

    results = {
        'message': 'success',
        'data': known_aoi.to_json(),
        'geometry': geometry,
        'regency': regency,
    }

    return make_response(jsonify(success_handler(results)), 200)