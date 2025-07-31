# application/models/geos/aoi.py
from application import db
from application.utils.common import get_date, map_attr, get_uuid

import uuid

from geoalchemy2 import Geometry

class Aoi(db.Model):
    __tablename__ = 'geos_aoi'
    id = db.Column(db.String(36), primary_key=True, default=get_uuid)
    geom = db.Column(Geometry(geometry_type='GEOMETRY', srid=4326))
    area_size = db.Column(db.Numeric(18, 4, asdecimal=False, decimal_return_scale=None), nullable=True)

    session_id = db.Column(db.String(36), db.ForeignKey('user_session.id'), index=True, nullable=False)
    session = db.relationship('Session', backref='aoi')

    created_date = db.Column(db.DateTime, default=get_date)
    modified_date = db.Column(db.DateTime, default=get_date, onupdate=get_date)
    
    def to_json(self, attr=[]):
        if attr:
            return map_attr(self, attr)
        
        return {
            'id': self.id,
            # 'geom': self.geom,
            'area_size': self.area_size,
            'session_id': self.session_id,

            'created_date': self.created_date.isoformat() if self.created_date else None,
            'modified_date': self.modified_date.isoformat() if self.modified_date else None,
        }