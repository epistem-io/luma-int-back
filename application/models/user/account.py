# application/models/users/account.py
from ... import db

from flask import current_app
from flask_login import UserMixin
from passlib.hash import sha256_crypt
from datetime import datetime, timedelta

import uuid
import os

from ...utils.common import get_date, map_attr

class Account(UserMixin, db.Model):
    __tablename__ = 'user_account'
    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(36), unique=True, default=uuid.uuid4)
    
    email = db.Column(db.String(256), nullable=False, index=True)
    password = db.Column(db.String(256), unique=False, nullable=False)

    is_admin = db.Column(db.Boolean, default=False)

    api_key = db.Column(db.String(255), unique=True, nullable=True)
    api_key_expires = db.Column(db.DateTime, default=get_date)

    rowstatus = db.Column(db.Integer, default=1)
    created_by = db.Column(db.String(100), nullable=True)
    created_date = db.Column(db.DateTime, default=get_date)
    modified_by = db.Column(db.String(100), nullable=True)
    modified_date = db.Column(db.DateTime, onupdate=get_date)

    def encode_api_key(self) -> None:
        self.api_key = sha256_crypt.hash(self.email + str(get_date()))
        self.api_key_expires = get_date() + timedelta(hours=24)

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
        }