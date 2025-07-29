# application/apis/user_apis/routes.py
from .. import user_apis_blueprint
from .... import db, login_manager
from flask import make_response, request, jsonify, current_app, g as g_var
from flask_login import current_user, login_user, logout_user, login_required

import uuid
import base64

from datetime import datetime, timedelta
from werkzeug.utils import secure_filename

from flask_cors import cross_origin

import gc
import os
import re

# models
from ....models.user.account import Account

# logic
from ....logic.user.account import AccountLogic

# utils
from ....utils.common import AppMessageException, get_date, set_attr, get_default_list_param
from ....utils.common import app_exception_handler, success_handler

@login_manager.user_loader
def load_user(user_id):
    return Account.query.filter_by(id=user_id).first()

@login_manager.request_loader
def load_user_from_request(request):
    api_key = request.headers.get('Authorization')
    if api_key:
        api_key = api_key.replace('EPISTEM ', '', 1)
        user = Account.query.filter_by(api_key=api_key).first()
        if user:
            if user.api_key_expires > get_date():
                return user
    return None

@user_apis_blueprint.route('/account/login', methods=['POST'])
@cross_origin()
def user_account_login():
    g_var.__api_name__ = 'user_account_login'
    g_var.__api_description__ = 'user account login'
    
    try:
        if not request.is_json:
            raise AppMessageException('please provide json data')
        
        data = request.get_json()

        email = data.get('email')
        password = data.get('password')

        if not email:
            raise AppMessageException('please input: email (text mandatory)')
        if not re.match(r'[^@]+@[^@]+\.[^@]+', email):
            raise AppMessageException('invalid input format: email')
        if not password:
            raise AppMessageException('please input: password (text mandatory)')
        
        return make_response(jsonify(success_handler(AccountLogic.login(email, password))), 200)
    except AppMessageException as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 400) # send bad request
    except Exception as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 500) # send internal error


