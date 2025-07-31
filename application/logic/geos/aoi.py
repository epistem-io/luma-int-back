# aoi.py
import ee
from application import db
from application.models.geos import Aoi

from shapely.geometry import shape
from shapely.wkt import dumps as shapely_to_wkt
from shapely.wkb import loads as shapely_to_wkb
from shapely.geometry import mapping

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

def ee_geometry_to_wkt(geometry:ee.Geometry):
    shapely_geom = shape(geometry.getInfo())
    return shapely_to_wkt(shapely_geom)

def wkb_to_ee_geometry(wkb:bytes):
    shapely_geom = shapely_to_wkb(wkb)
    return ee.Geometry(mapping(shapely_geom))