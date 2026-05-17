# application/logic/user/account.py
import os
import logging

from application import db
from flask import current_app
from flask_login import login_user

from application.models.user import Account
from application.models.master import Settings
from application.utils.common import AppMessageException, get_date, render_html_template
from application.utils.mail import send_email

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'utils', '_templates')


class AccountLogic:

    @staticmethod
    def login(email: str, password: str) -> dict:
        known_user = Account.query.filter_by(email=email).first()
        if not known_user or not known_user.check_password(password):
            raise AppMessageException('email or password does not match')

        if not known_user.is_active:
            raise AppMessageException('account not yet activated — please set your password via the verification email')

        if not known_user.api_key or get_date() > known_user.api_key_expires:
            known_user.encode_api_key()

        db.session.commit()
        login_user(known_user)

        return {
            'api_key': known_user.api_key,
            'api_key_expires': known_user.api_key_expires.isoformat(),
            'user': known_user.to_json(attr=[])
        }

    @staticmethod
    def signup(email: str, fullname: str, organization_name: str = None) -> dict:
        existing = Account.query.filter_by(email=email).first()
        if existing:
            if existing.is_active:
                raise AppMessageException('email already registered')
            token_expired = (not existing.signup_token_expires) or (get_date() > existing.signup_token_expires)
            if token_expired:
                existing.encode_signup_token()
                db.session.commit()
            try:
                AccountLogic._send_signup_email(existing)
            except Exception as e:
                logging.error('signup email resend failed: {}'.format(str(e)))
            return {'message': 'verification email sent'}

        account = Account(
            email=email,
            fullname=fullname,
            organization_name=organization_name,
            password='__unset__',
            is_active=False,
        )
        account.encode_signup_token()
        db.session.add(account)
        db.session.commit()

        try:
            AccountLogic._send_signup_email(account)
        except Exception as e:
            logging.error('signup email send failed: {}'.format(str(e)))

        return {'message': 'account created — verification email sent'}

    @staticmethod
    def resend_verification(email: str) -> dict:
        account = Account.query.filter_by(email=email).first()
        if not account:
            raise AppMessageException('email not registered')
        if account.is_active:
            raise AppMessageException('account already active — please log in')

        token_expired = (not account.signup_token_expires) or (get_date() > account.signup_token_expires)
        if token_expired:
            account.encode_signup_token()
            db.session.commit()

        try:
            AccountLogic._send_signup_email(account)
        except Exception as e:
            logging.error('signup email resend failed: {}'.format(str(e)))

        return {'message': 'verification email sent'}

    @staticmethod
    def set_password(token: str, password: str) -> dict:
        account = Account.query.filter_by(signup_token=token).first()
        if not account:
            raise AppMessageException('invalid or expired token')
        if get_date() > account.signup_token_expires:
            raise AppMessageException('token has expired — please request a new verification email')

        account.password = password
        account.encode_password()
        account.is_active = True
        account.signup_token = None
        account.signup_token_expires = None
        db.session.commit()

        return {'message': 'password set — you can now log in'}

    @staticmethod
    def _send_signup_email(account: Account):
        setting = Settings.find_by_name('SIGNUP_SET_PASSWORD_URL')
        if not setting or not setting.value.strip():
            raise ValueError('SIGNUP_SET_PASSWORD_URL not configured in settings table')

        set_password_url = setting.value.strip().rstrip('/') + '/' + account.signup_token

        body = render_html_template(
            os.path.join(_TEMPLATE_DIR, 'signup_verification.html'),
            full_name=account.fullname or account.email,
            set_password_url=set_password_url,
        )

        send_email(account.email, '[Epistem] Verify your account', body)
