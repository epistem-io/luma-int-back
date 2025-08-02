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
        'pool_size': 30, # custom pool size
        'max_overflow': 0, # as recommended in https://docs.sqlalchemy.org/en/20/core/pooling.html
    }

    GCS_BUCKET_NAME = os.environ.get('GCS_BUCKET_NAME')

class DevelopmentConfig(Config):
    ENV = "development"
    DEBUG = True
    SQLALCHEMY_ECHO = True


class ProductionConfig(Config):
    ENV = "production"
    DEBUG = False
    SQLALCHEMY_ECHO = False
