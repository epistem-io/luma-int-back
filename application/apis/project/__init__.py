from flask import Blueprint

project_apis_blueprint = Blueprint('project_apis', __name__)

from . import routes