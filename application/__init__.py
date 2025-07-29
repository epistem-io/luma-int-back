# application/__init__.py
import config
import os, gc, sys, ee, json
from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS

import logging
logging.basicConfig(
    stream=sys.stdout, 
    level=logging.DEBUG,
    format='%(asctime)s - %(process)d - %(levelname)s - %(message)s',
)

try:
    credentials = ee.ServiceAccountCredentials(
        json.loads(open(os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'), 'r').read())['client_email'],
        os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    )
except Exception as e:
    logging.error('error on ee credentials: {}'.format(str(e)))
    from google.auth import compute_engine
    credentials = compute_engine.Credentials(scopes=[ "https://www.googleapis.com/auth/earthengine" ])
finally:
    ee.Initialize(credentials)

db = SQLAlchemy()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    cors = CORS(app)
    environment_configuration = os.environ['CONFIGURATION_SETUP']
    app.config.from_object(environment_configuration)
    app.config['CORS_HEADERS'] = 'Content-Type'
    app.config['RESTX_MASK_SWAGGER'] = False

    db.init_app(app)
    login_manager.init_app(app)

    with app.app_context():
        @app.route('/', methods=['GET']) # for healthcheck
        def check():
            return 'ok'

        # Register blueprints
        from .apis.user import user_apis_blueprint
        app.register_blueprint(user_apis_blueprint, url_prefix='/users')

        from .apis.geos import geos_apis_blueprint
        app.register_blueprint(geos_apis_blueprint, url_prefix='/geos')

        # from .apis import swagger_apis_blueprint
        # app.register_blueprint(swagger_apis_blueprint, url_prefix='/')
    
    return app
