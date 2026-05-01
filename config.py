# config.py
import os
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DB_SQLALCHEMY_URI')
    
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'max_overflow': 5,
        'pool_pre_ping': True,       # test connection before use, discard if dead
        'pool_recycle': 120,
        'pool_timeout': 30,
        'connect_args': {
            'keepalives': 1,
            'keepalives_idle': 30,
            'keepalives_interval': 10,
            'keepalives_count': 5,
        }
    }

    GCS_BUCKET_NAME = os.environ.get('GCS_BUCKET_NAME')

    MAIL_SMTP_HOST = os.environ.get('MAIL_SMTP_HOST', 'smtp.gmail.com')
    MAIL_SMTP_PORT = int(os.environ.get('MAIL_SMTP_PORT', 587))
    MAIL_SENDER = os.environ.get('MAIL_SENDER', 'webdev@epistem.io')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')

class DevelopmentConfig(Config):
    ENV = "development"
    DEBUG = True
    SQLALCHEMY_ECHO = True


class ProductionConfig(Config):
    ENV = "production"
    DEBUG = False
    SQLALCHEMY_ECHO = False
