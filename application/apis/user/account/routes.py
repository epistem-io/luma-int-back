# application/apis/user_apis/routes.py
from application import db, login_manager
from application.apis.user import user_apis_blueprint
from flask import make_response, request, jsonify, current_app, g as g_var
from flask_login import current_user, login_user, logout_user, login_required

from flask_cors import cross_origin

import re

# models
from application.models.user import Account

# logic
from application.logic.user.account import AccountLogic

# utils
from application.utils.common import AppMessageException, get_date, set_attr, get_default_list_param
from application.utils.common import app_exception_handler, success_handler, ErrorCodeEnum

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

@user_apis_blueprint.route('/account/me', methods=['GET'])
@cross_origin()
def user_account_me():
    g_var.__api_name__ = 'user_account_me'
    g_var.__api_description__ = 'get current user'

    try:
        if not current_user.is_authenticated:
            return make_response(jsonify(app_exception_handler(AppMessageException('not authenticated', error=ErrorCodeEnum.ERR_NOAUTH), services=g_var.__api_name__)), 401)
        return make_response(jsonify(success_handler(current_user.to_json())), 200)
    except Exception as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 500)


@user_apis_blueprint.route('/account/signup', methods=['POST'])
@cross_origin()
def user_account_signup():
    g_var.__api_name__ = 'user_account_signup'
    g_var.__api_description__ = 'user account signup'

    try:
        if not request.is_json:
            raise AppMessageException('please provide json data')

        data = request.get_json()

        email = data.get('email')
        fullname = data.get('fullname')
        organization_name = data.get('organization_name')

        if not email:
            raise AppMessageException('please input: email (text mandatory)')
        if not re.match(r'[^@]+@[^@]+\.[^@]+', email):
            raise AppMessageException('invalid input format: email')
        if not fullname:
            raise AppMessageException('please input: fullname (text mandatory)')
        if not organization_name:
            raise AppMessageException('please input: organization_name (text mandatory)')

        return make_response(jsonify(success_handler(AccountLogic.signup(email, fullname, organization_name))), 201)
    except AppMessageException as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 400)
    except Exception as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 500)


@user_apis_blueprint.route('/account/resend-verification', methods=['POST'])
@cross_origin()
def user_account_resend_verification():
    g_var.__api_name__ = 'user_account_resend_verification'
    g_var.__api_description__ = 'resend signup verification email'

    try:
        if not request.is_json:
            raise AppMessageException('please provide json data')

        data = request.get_json()
        email = data.get('email')

        if not email:
            raise AppMessageException('please input: email (text mandatory)')
        if not re.match(r'[^@]+@[^@]+\.[^@]+', email):
            raise AppMessageException('invalid input format: email')

        return make_response(jsonify(success_handler(AccountLogic.resend_verification(email))), 200)
    except AppMessageException as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 400)
    except Exception as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 500)


@user_apis_blueprint.route('/account/set-password/<string:token>', methods=['POST'])
@cross_origin()
def user_account_set_password(token):
    g_var.__api_name__ = 'user_account_set_password'
    g_var.__api_description__ = 'set password via signup token'

    try:
        if not request.is_json:
            raise AppMessageException('please provide json data')

        data = request.get_json()
        password = data.get('password')

        if not password:
            raise AppMessageException('please input: password (text mandatory)')
        if len(password) < 8:
            raise AppMessageException('password must be at least 8 characters')

        return make_response(jsonify(success_handler(AccountLogic.set_password(token, password))), 200)
    except AppMessageException as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 400)
    except Exception as e:
        return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 500)


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


