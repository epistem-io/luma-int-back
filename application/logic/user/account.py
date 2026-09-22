# application/logic/user/account.py
import os
import logging
from datetime import timedelta
from html import escape

from application import db
from flask import current_app
from flask_login import login_user

from application.models.user import Account
from application.models.master import Settings
from application.utils.common import AppMessageException, get_date, render_html_template
from application.utils.mail import send_email
from application.logic.user.invite_rules import (
    INVITE_TOKEN_HOURS,
    LOGIN_CODE_SECONDS,
    MAX_INVITES_PER_DAY,
    can_invite,
    clean_optional,
    is_expired,
    resolve_fullname,
)

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'utils', '_templates')


class AccountLogic:

    @staticmethod
    def login(email: str, password: str) -> dict:
        known_user = Account.query.filter_by(email=email).first()
        if not known_user or not known_user.check_password(password):
            raise AppMessageException('email or password does not match')

        if not known_user.is_active:
            raise AppMessageException('account not yet activated — please set your password via the verification email')

        return AccountLogic._auth_payload(known_user)

    @staticmethod
    def _auth_payload(known_user: Account) -> dict:
        """The login response; shared by password login and the login-code exchange."""
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
    def _account_for_signup_token(token: str) -> Account:
        account = Account.query.filter_by(signup_token=token).first() if token else None
        if not account:
            raise AppMessageException('invalid or expired token')
        if is_expired(account.signup_token_expires, get_date()):
            raise AppMessageException('token has expired — please request a new verification email')
        return account

    @staticmethod
    def get_set_password_info(token: str) -> dict:
        """Who a set-password token belongs to; prefills the set-password form."""
        account = AccountLogic._account_for_signup_token(token)
        inviter = Account.query.filter_by(id=account.invited_by).first() if account.invited_by else None
        return {
            'email': account.email,
            'fullname': account.fullname or '',
            'organization_name': account.organization_name or '',
            'invited': bool(account.invited_by),
            'invited_by': (inviter.fullname or inviter.email) if inviter else None,
        }

    @staticmethod
    def set_password(token: str, password: str, fullname: str = None, organization_name: str = None) -> dict:
        # The account comes from the token only; an email is never read from the request.
        account = AccountLogic._account_for_signup_token(token)

        try:
            account.fullname = resolve_fullname(account.fullname, fullname)
            organization = clean_optional(organization_name)
        except ValueError as e:
            raise AppMessageException(str(e))
        if organization:
            account.organization_name = organization

        account.password = password
        account.encode_password()
        account.is_active = True
        account.signup_token = None
        account.signup_token_expires = None
        # Lets the set-password page hand the user to the Luma app already logged in.
        account.encode_login_code(LOGIN_CODE_SECONDS)
        db.session.commit()

        return {'message': 'password set — you can now log in', 'login_code': account.login_code}

    @staticmethod
    def exchange_login_code(code: str) -> dict:
        account = Account.query.filter_by(login_code=code).first() if code else None
        if not account:
            raise AppMessageException('invalid or expired login code')

        expired = is_expired(account.login_code_expires, get_date())
        account.clear_login_code()          # single use, whatever the outcome
        if expired or not account.is_active:
            db.session.commit()
            raise AppMessageException('invalid or expired login code')

        return AccountLogic._auth_payload(account)   # commits

    @staticmethod
    def create_invited_account(email: str, inviter_id: str) -> Account:
        """Inactive account for a share recipient. Flushes only — the caller's
        transaction (share_project) commits or rolls back account + fork together."""
        since = get_date() - timedelta(hours=24)
        sent = Account.query.filter(
            Account.invited_by == inviter_id, Account.created_date > since
        ).count()
        if not can_invite(sent):
            raise AppMessageException(
                'invite limit reached — you can invite up to {} new people per day'.format(MAX_INVITES_PER_DAY)
            )

        account = Account(
            email=email,
            fullname=None,
            password='__unset__',
            is_active=False,
            invited_by=inviter_id,
        )
        account.encode_signup_token(hours=INVITE_TOKEN_HOURS)
        db.session.add(account)
        db.session.flush()
        return account

    @staticmethod
    def ensure_invite_token(account: Account) -> None:
        """Re-issue the set-password token of a still-inactive account when it
        has lapsed. No commit — the caller commits."""
        if not account.signup_token or is_expired(account.signup_token_expires, get_date()):
            account.encode_signup_token(hours=INVITE_TOKEN_HOURS)

    @staticmethod
    def _setting_url(name: str) -> str:
        setting = Settings.find_by_name(name)
        if not setting or not setting.value.strip():
            raise ValueError('{} not configured in settings table'.format(name))
        return setting.value.strip().rstrip('/')

    @staticmethod
    def send_invite_email(account: Account, inviter_name: str, project_name: str):
        set_password_url = AccountLogic._setting_url('SIGNUP_SET_PASSWORD_URL') + '/' + account.signup_token

        body = render_html_template(
            os.path.join(_TEMPLATE_DIR, 'project_invite.html'),
            inviter_name=escape(inviter_name),
            project_name=escape(project_name),
            set_password_url=set_password_url,
        )

        send_email(account.email, '[Epistem] {} shared a Luma project with you'.format(inviter_name), body)

    @staticmethod
    def send_share_notification(account: Account, sharer_name: str, project_name: str):
        body = render_html_template(
            os.path.join(_TEMPLATE_DIR, 'project_shared.html'),
            full_name=escape(account.fullname or account.email),
            sharer_name=escape(sharer_name),
            project_name=escape(project_name),
            luma_url=AccountLogic._setting_url('LUMA_APP_URL'),
        )

        send_email(account.email, '[Epistem] {} shared a Luma project with you'.format(sharer_name), body)

    @staticmethod
    def _send_signup_email(account: Account):
        set_password_url = AccountLogic._setting_url('SIGNUP_SET_PASSWORD_URL') + '/' + account.signup_token

        body = render_html_template(
            os.path.join(_TEMPLATE_DIR, 'signup_verification.html'),
            full_name=account.fullname or account.email,
            set_password_url=set_password_url,
        )

        send_email(account.email, '[Epistem] Verify your account', body)
