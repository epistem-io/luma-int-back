# application/apis/geos/test_ee/routes.py
from .. import geos_apis_blueprint
from .... import db
from flask import make_response, request, jsonify, current_app, g as g_var
from flask_login import current_user

from datetime import datetime, timedelta
from flask_cors import cross_origin

import gc
import os

# models

# logic
from ....logic.geos.test_ee import TestEarthengineLogic

# utils
from ....utils.common import AppMessageException, get_date, set_attr, get_default_list_param
from ....utils.common import app_exception_handler, success_handler


@geos_apis_blueprint.route('/test-ee', methods=['GET'])
@cross_origin()
def geos_test_earthengine():
    g_var.__api_name__ = 'geos_test_earthengine'
    g_var.__api_description__ = 'geos test earthengine'
    
    try:
        return make_response(jsonify(success_handler(TestEarthengineLogic.test_ee())), 200)
    except AppMessageException as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 400) # send bad request
    except Exception as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 500) # send internal error


@geos_apis_blueprint.route('/test-ee/v2', methods=['GET'])
@cross_origin()
def geos_test_earthengine_v2():
    g_var.__api_name__ = 'geos_test_earthengine_v2'
    g_var.__api_description__ = 'geos test earthengine v2'
    
    try:
        return make_response(jsonify(success_handler(TestEarthengineLogic.test_ee_v2())), 200)
    except AppMessageException as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 400) # send bad request
    except Exception as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 500) # send internal error
