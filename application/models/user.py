# application/models/users/account.py
from sqlalchemy import Nullable
from application import db

from flask import current_app
from flask_login import UserMixin
from passlib.hash import sha256_crypt
from datetime import datetime, timedelta
from sqlalchemy.dialects.postgresql import JSONB

import uuid
import os

from application.utils.common import get_date, map_attr, get_uuid

class Account(UserMixin, db.Model):
    __tablename__ = 'user_account'
    id = db.Column(db.String(36), primary_key=True, default=get_uuid)
    
    email = db.Column(db.String(256), nullable=False, index=True)
    password = db.Column(db.String(256), unique=False, nullable=False)
    fullname = db.Column(db.String(256), nullable=True)
    organization_name = db.Column(db.String(256), nullable=True)

    is_admin = db.Column(db.Boolean, default=False)

    api_key = db.Column(db.String(255), unique=True, nullable=True)
    api_key_expires = db.Column(db.DateTime, default=get_date)

    signup_token = db.Column(db.String(255), unique=True, nullable=True)
    signup_token_expires = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=False)

    rowstatus = db.Column(db.Integer, default=1)
    created_by = db.Column(db.String(100), nullable=True)
    created_date = db.Column(db.DateTime, default=get_date)
    modified_by = db.Column(db.String(100), nullable=True)
    modified_date = db.Column(db.DateTime, onupdate=get_date)

    def encode_api_key(self) -> None:
        self.api_key = sha256_crypt.hash(self.email + str(get_date()))
        self.api_key_expires = get_date() + timedelta(hours=24)

    def encode_signup_token(self) -> None:
        import uuid
        self.signup_token = str(uuid.uuid4())
        self.signup_token_expires = get_date() + timedelta(hours=24)

    def encode_password(self) -> None:
        self.password = sha256_crypt.hash(self.password)
    
    def check_password(self, password:str) -> bool:
        return sha256_crypt.verify(password, self.password)

    def __repr__(self):
        return '<User %r>' % (self.email)

    def to_json(self, attr=[]) -> dict:
        if attr:
            return map_attr(self, attr)
        
        return {
            'uid': self.uid,
            'email': self.email,
            'fullname': self.fullname,
            'organization_name': self.organization_name
        }


class Session(db.Model):
    __tablename__ = 'user_session'
    id = db.Column(db.String(36), primary_key=True, default=get_uuid)
    account_id = db.Column(db.String(36), db.ForeignKey('user_account.id'), index=True, nullable=True)
    account = db.relationship('Account', backref='session')
    
    created_date = db.Column(db.DateTime, default=get_date)
    modified_date = db.Column(db.DateTime, onupdate=get_date)

    def to_json(self, attr=[]):
        if attr:
            return map_attr(self, attr)
        
        return {
            'id': self.id,
            'account_id': self.account_id,
        }


class GeeAsset(db.Model):
    __tablename__ = 'user_gee_asset'
    id = db.Column(db.String(36), primary_key=True, default=get_uuid)
    session_id = db.Column(db.String(36), db.ForeignKey('user_session.id'), index=True, nullable=False)
    session = db.relationship('Session', backref='gee_asset')
    
    asset_id = db.Column(db.String(256), nullable=True)
    
    created_date = db.Column(db.DateTime, default=get_date)
    modified_date = db.Column(db.DateTime, default=get_date, onupdate=get_date)
    
    def to_json(self, attr=[]):
        if attr:
            return map_attr(self, attr)
        
        return {
            'id': self.id,
            'session_id': self.session_id,
            'asset_id': self.asset_id,

            'created_date': self.created_date.isoformat() if self.created_date else None,
            'modified_date': self.modified_date.isoformat() if self.modified_date else None,
        }


class ErrorLog(db.Model):
    __tablename__ = 'system_error_log'
    id = db.Column(db.String(36), primary_key=True, default=get_uuid)

    api_name = db.Column(db.String(256), nullable=True)
    session_id = db.Column(db.String(36), nullable=True)
    request_url = db.Column(db.Text, nullable=True)
    request_method = db.Column(db.String(16), nullable=True)
    request_data = db.Column(JSONB, nullable=True)
    trace = db.Column(db.Text, nullable=True)

    created_date = db.Column(db.DateTime, default=get_date)