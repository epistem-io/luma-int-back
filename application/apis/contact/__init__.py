# application/apis/contact/__init__.py
from flask import Blueprint

contact_apis_blueprint = Blueprint('contact_apis', __name__)

from . import routes
