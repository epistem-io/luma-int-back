# application/apis/geos/aoi/routes.py
from application import db
from application.apis.geos import geos_apis_blueprint
from flask import make_response, request, jsonify, current_app, g as g_var
from flask_login import current_user
from flask_cors import cross_origin

import uuid

# models
from application.models.geos import Aoi
from application.models.user import Session

# logic
from application.logic.geos import aoi as logic

# utils
from application.utils.common import AppMessageException, get_date, set_attr, get_default_list_param
from application.utils.common import app_exception_handler, success_handler


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
        
        known_session = Session.query.filter_by(id=session_id).first()
        if not known_session:
            known_session = Session()

            if current_user.is_authenticated:
                known_session.account_id = current_user.id
            
            db.session.add(known_session)
            db.session.flush()
            db.session.refresh(known_session)

        known_aoi = logic.aoi(known_session, geometry)

        db.session.commit()

        results = {
            'message': 'success',
            'data': known_aoi.to_json()
        }

        return make_response(jsonify(success_handler(results)), 200)
    except AppMessageException as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 400) # send bad request
    except Exception as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 500) # send internal error

