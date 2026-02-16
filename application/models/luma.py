# application/models/geos/aoi.py
from venv import create
from application import db
from application.utils.common import get_date, map_attr, get_uuid

from geoalchemy2 import Geometry
import json

class Luma(db.Model):
    __tablename__ = 'luma_general'
    id = db.Column(db.String(36), primary_key=True, default=get_uuid)
    
    session_id = db.Column(db.String(36), db.ForeignKey('user_session.id'), index=True, nullable=False)
    session = db.relationship('Session', backref='luma')

    start_date = db.Column(db.DateTime, nullable=True)
    end_date = db.Column(db.DateTime, nullable=True)
    landsat_version = db.Column(db.String(10), nullable=True)
    cloud_cover = db.Column(db.Integer, nullable=True)
    
    created_date = db.Column(db.DateTime, default=get_date)
    modified_date = db.Column(db.DateTime, default=get_date, onupdate=get_date)
    
    def to_json(self, attr=[]):
        if attr:
            return map_attr(self, attr)
        
        return {
            'id': self.id,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'landsat_version': self.landsat_version,
            'cloud_cover': self.cloud_cover,
            'session_id': self.session_id,

            'created_date': self.created_date.isoformat() if self.created_date else None,
            'modified_date': self.modified_date.isoformat() if self.modified_date else None,
        }


class Layers(db.Model):
    __tablename__ = 'luma_layers'
    id = db.Column(db.String(36), primary_key=True, default=get_uuid)
    
    session_id = db.Column(db.String(36), db.ForeignKey('user_session.id'), index=True, nullable=False)
    session = db.relationship('Session', backref='luma_layers')

    name = db.Column(db.String(256), nullable=True)
    code = db.Column(db.String(20), nullable=True, index=True)
    url = db.Column(db.String(256), nullable=True)

    created_date = db.Column(db.DateTime, default=get_date)
    modified_date = db.Column(db.DateTime, default=get_date, onupdate=get_date)

    def to_json(self, attr=[]):
        return {
            'id': self.id,
            'session_id': self.session_id,

            'name': self.name,
            'code': self.code,
            'url': self.url,

            'created_date': self.created_date.isoformat() if self.created_date else None,
            'modified_date': self.modified_date.isoformat() if self.modified_date else None,
        }


class LulcClass(db.Model):
    __tablename__ = 'luma_lulc_class'
    id = db.Column(db.String(36), primary_key=True, default=get_uuid)
    
    session_id = db.Column(db.String(36), db.ForeignKey('user_session.id'), index=True, nullable=False)
    session = db.relationship('Session', backref='luma_lulc_class')

    class_id = db.Column(db.Integer, nullable=True)
    class_name = db.Column(db.String(256), nullable=True)
    class_color = db.Column(db.String(20), nullable=True)

    created_date = db.Column(db.DateTime, default=get_date)
    modified_date = db.Column(db.DateTime, default=get_date, onupdate=get_date)

    def to_json(self, attr=[]):
        return {
            'id': self.id,
            'session_id': self.session_id,

            'class_id': self.class_id,
            'class_name': self.class_name,
            'class_color': self.class_color,

            'created_date': self.created_date.isoformat() if self.created_date else None,
            'modified_date': self.modified_date.isoformat() if self.modified_date else None,
        }


class TrainingData(db.Model):
    __tablename__ = 'luma_training_data'
    id = db.Column(db.Integer, primary_key=True)

    session_id = db.Column(db.String(36), db.ForeignKey('user_session.id'), index=True, nullable=False)
    session = db.relationship('Session', backref='luma_training_data')
    
    class_id = db.Column(db.Integer, nullable=True)
    class_name = db.Column(db.String(256), nullable=True)
    class_color = db.Column(db.String(20), nullable=True)
    geom = db.Column(Geometry(geometry_type='GEOMETRY', srid=4326))

    created_date = db.Column(db.DateTime, default=get_date)
    modified_date = db.Column(db.DateTime, default=get_date, onupdate=get_date)

    def to_json(self, attr=[]):
        return {
            'id': self.id,
            'session_id': self.session_id,

            'class_id': self.class_id,
            'class_name': self.class_name,
            'class_color': self.class_color,

            'created_date': self.created_date.isoformat() if self.created_date else None,
            'modified_date': self.modified_date.isoformat() if self.modified_date else None,
        }
    
    @staticmethod
    def get_by_session_id(session_id, to_json=False):
        dt = db.session.query(
            TrainingData.session_id,
            TrainingData.class_id,
            TrainingData.class_name,
            TrainingData.class_color,
            TrainingData.created_date,
            TrainingData.modified_date,
            db.func.ST_AsGeoJSON(TrainingData.geom).label("geom")
        ).filter_by(session_id=session_id).all()

        if to_json:
            return [
                {
                    **row._asdict(),
                    "geom": json.loads(row.geom) if row.geom else None,
                    "created_date": row.created_date.isoformat() if row.created_date else None,
                    "modified_date": row.modified_date.isoformat() if row.modified_date else None,
                }
                for row in dt
            ]
        
        return dt