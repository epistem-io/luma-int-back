# application/apis/user_apis/routes.py
from ... import db, login_manager
from flask import make_response, request, jsonify, current_app, g as g_var
from flask_login import current_user, login_user, logout_user, login_required

from datetime import datetime, timedelta
from passlib.hash import sha256_crypt

import os
import json
import uuid
import base64

# models
from ...models.user.account import Account

# utils
from ...utils.common import AppMessageException, get_date, set_attr, get_default_list_param
from ...utils.common import app_exception_handler, success_handler


class AccountLogic:

    @staticmethod
    def login(email:str, password:str) -> dict:
        known_user = Account.query.filter_by(email=email).first()
        if not known_user or not known_user.check_password(password):
            raise AppMessageException('email or password does not match')
        
        if not known_user.api_key or get_date() > known_user.api_key_expires:
                known_user.encode_api_key()

        db.session.commit()
        login_user(known_user)

        return {
            'api_key': known_user.api_key,
            'api_key_expires': known_user.api_key_expires.isoformat(),
            'user': known_user.to_json(attr=[])
        }