# application/apis/geos/lulc_classification/routes.py
from application import db
from application.apis.geos import geos_apis_blueprint
from flask import make_response, request, jsonify, current_app, g as g_var
from flask_login import current_user
from flask_cors import cross_origin

import uuid
import arrow

# models
from application.models.geos import Aoi
from application.models.user import Session

# logic
from application.logic.geos import f05_generate_lulc_map as logic
from application.logic.geos import aoi as aoi_logic

# utils
from application.utils.common import AppMessageException, get_date, set_attr, get_default_list_param
from application.utils.common import app_exception_handler, success_handler


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

        results = logic.f05_generate_lulc_map(
            aoi=aoi,
            start_date=start_date,
            end_date=end_date,
            landsat_version=landsat_version,
            cloud_cover=cloud_cover
        )

        return make_response(jsonify(success_handler(results)), 200)
    except AppMessageException as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 400) # send bad request
    except Exception as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 500) # send internal error

