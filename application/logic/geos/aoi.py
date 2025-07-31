# aoi.py
import ee
from application import db
from application.models.geos import Aoi

from shapely.geometry import shape
from shapely.wkt import dumps as shapely_to_wkt

import uuid

def aoi(known_session, geometry):
    geometry = ee.Geometry(geometry)

    shapely_geom = shape(geometry.getInfo())
    wkt_geom = shapely_to_wkt(shapely_geom)

    known_aoi = Aoi.query.filter_by(session_id=known_session.id).first()
    if not known_aoi:
        known_aoi = Aoi()
        known_aoi.session_id = known_session.id
    
    known_aoi.geom = wkt_geom
    known_aoi.area_size = geometry.area().getInfo()
    
    db.session.add(known_aoi)
    
    return known_aoi