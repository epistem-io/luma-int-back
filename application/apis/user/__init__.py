# application/apis/user_apis/__init__.py
from flask import Blueprint, Response, request

user_apis_blueprint = Blueprint('user_apis', __name__)

from .account import routes

# restx
from flask_restx import Api
from .account import api as docs_account

authorizations = {
    'api_key': {
        'type': 'apiKey',
        'in': 'header',
        'name': 'Authorization',
        'description': 'Sample: EPISTEM {the api key}'
    }
}

api_extension = Api(
    user_apis_blueprint,
    authorizations=authorizations,
    title='Epistem User APIs',
    version='1.0',
    doc='/',
    security='api_key',
    description=''
)

api_extension.add_namespace(docs_account)