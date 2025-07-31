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
from application.logic.user import session as session_logic

# utils
from application.utils.common import AppMessageException, get_date, set_attr, get_default_list_param
from application.utils.common import app_exception_handler, success_handler
from application.utils.common import allowed_file


@geos_apis_blueprint.route('/aoi', methods=['POST'])
@cross_origin()
def geos_aoi():
    g_var.__api_name__ = 'geos_aoi'
    g_var.__api_description__ = 'geos aoi'
    
    try:
        if not request.is_json:
            raise AppMessageException('please provide json data')
        
        data = request.get_json()
        geometry = data.get('geometry')
        session_id = data.get('session_id')

        if not geometry:
            raise AppMessageException('please provide geometry')
        
        known_session = session_logic.init_session(session_id)

        known_aoi = logic.aoi(known_session, geometry)

        db.session.commit()

        results = {
            'message': 'success',
            'data': known_aoi.to_json(),
            'geometry': geometry
        }

        return make_response(jsonify(success_handler(results)), 200)
    except AppMessageException as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 400) # send bad request
    except Exception as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 500) # send internal error


@geos_apis_blueprint.route('/aoi/upload', methods=['POST'])
@cross_origin()
def geos_aoi_upload():
    g_var.__api_name__ = 'geos_aoi_upload'
    g_var.__api_description__ = 'geos aoi upload'
    
    try:
        data = request.form

        session_id = data.get('session_id')
        file = request.files.get('file')

        if not file:
            raise AppMessageException('No selected file')
        if not file.filename:
            raise appmessageexception('No selected file')
        if not allowed_file(file.filename, {'kml', 'kmz', 'zip'}):
            raise AppMessageException('Invalid file format, only ZIP, KML or KMZ files are allowed')
        
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
    except AppMessageException as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 400) # send bad request
    except Exception as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 500) # send internal error