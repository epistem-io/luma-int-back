# application/__init__.py
import config
import os, gc, sys # , ee, json
from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS

from werkzeug.middleware.proxy_fix import ProxyFix
from luma_ge import auto_initialize

import logging
logging.basicConfig(
    stream=sys.stdout, 
    level=logging.DEBUG,
    format='%(asctime)s - %(process)d - %(levelname)s - %(message)s',
)

# try:
#     credentials = ee.ServiceAccountCredentials(
#         json.loads(open(os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'), 'r').read())['client_email'],
#         os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
#     )
# except Exception as e:
#     logging.error('error on ee credentials: {}'.format(str(e)))
#     from google.auth import compute_engine
#     credentials = compute_engine.Credentials(scopes=[ "https://www.googleapis.com/auth/earthengine" ])
# finally:
#     ee.Initialize(credentials)

try:
    success = auto_initialize()
    if not success:
        print("Failed to initialize Luma Earth Engine")
        exit()
except Exception as e:
    print(f"Earth Engine initialization error: {e}")
    exit()

db = SQLAlchemy()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    cors = CORS(app)
    environment_configuration = os.environ['CONFIGURATION_SETUP']
    app.config.from_object(environment_configuration)
    app.config['CORS_HEADERS'] = 'Content-Type'

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1, x_proto=1, x_port=1, x_prefix=1)

    db.init_app(app)
    login_manager.init_app(app)

    with app.app_context():
        @app.route('/api/v1/health', methods=['GET']) # for healthcheck
        def check():
            return 'ok'

        # Register blueprints
        from .apis.user import user_apis_blueprint
        app.register_blueprint(user_apis_blueprint, url_prefix='/api/v1/users')
        app.register_blueprint(user_apis_blueprint, url_prefix='/users', name="users_legacy") # for legacy API, to be deleted

        from .apis.geos import geos_apis_blueprint
        app.register_blueprint(geos_apis_blueprint, url_prefix='/api/v1/geos')
        app.register_blueprint(geos_apis_blueprint, url_prefix='/geos', name="geos_legacy") # for legacy API, to be deleted

        from .apis.luma import luma_apis_blueprint
        app.register_blueprint(luma_apis_blueprint, url_prefix='/api/v1/luma')

        from .apis.contact import contact_apis_blueprint
        app.register_blueprint(contact_apis_blueprint, url_prefix='/api/v1/contact')

        from .apis import apis_blueprint
        app.register_blueprint(apis_blueprint, url_prefix='/api/v1')
    
    return app
