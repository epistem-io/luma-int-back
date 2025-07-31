# application/apis/geos/__init__.py
from flask import Blueprint, Response, request

geos_apis_blueprint = Blueprint('geos_apis', __name__)

from .test_ee import routes
from .aoi import routes
from .lulc_classification import routes
