# aoi.py
import ee
from application import db
from application.models.geos import Aoi

from shapely.geometry import shape
from shapely.wkt import dumps as shapely_to_wkt
from shapely.wkb import loads as shapely_to_wkb
from shapely.geometry import mapping

import uuid
import zipfile
import os
import fiona
import pandas as pd
import geopandas as gpd
import json

from pyproj import CRS
from shapely import Polygon, MultiPolygon
from shapely import wkb, box
from shapely.ops import unary_union
from shapely.geometry import shape
from fiona.drvsupport import supported_drivers

from application.utils.common import AppMessageException, remove_tree_file

def aoi(known_session, geometry):
    geometry = ee.Geometry(geometry)

    shapely_geom = shape(geometry.getInfo())
    wkt_geom = shapely_to_wkt(shapely_geom)

    known_aoi = Aoi.query.filter_by(session_id=known_session.id).first()
    if not known_aoi:
        known_aoi = Aoi()
        known_aoi.session_id = known_session.id
    
    known_aoi.geom = wkt_geom

    area_size = geometry.area().getInfo()
    known_aoi.area_size = (area_size / 1000) if area_size else 0
    
    db.session.add(known_aoi)
    
    return known_aoi

def ee_geometry_to_wkt(geometry:ee.Geometry):
    shapely_geom = shape(geometry.getInfo())
    return shapely_to_wkt(shapely_geom)

def wkb_to_ee_geometry(wkb:bytes):
    shapely_geom = shapely_to_wkb(wkb)
    return ee.Geometry(mapping(shapely_geom))

def process_zip_and_get_polygon(filepath, session_id, upload_folder):
    temp_dir = 'temp_zip_extraction'
    extracted_filepath = os.path.join(upload_folder, session_id, temp_dir) # "Uploaded-File/"+session_id+"/"+temp_dir
    os.makedirs(extracted_filepath, exist_ok=True)
    
    try:
        with zipfile.ZipFile(filepath, 'r') as zip_file:
            zip_file.extractall(extracted_filepath)

        # check if ada file shp didalem zip, return error if not
        filename = None
        for root, dirs, files in os.walk(extracted_filepath):
            for file in files:
                if not file.startswith('.') and file.endswith('.shp'):
                    filename = os.path.join(root, file)
        if not filename:
            raise AppMessageException('No .shp file found in the ZIP file.')

        # check if crs epsg != 4326 return error
        aoi = gpd.read_file(filename)
        aoi = aoi.to_crs(4326)
        """ 
        gdf = gpd.read_file(filename)
        gdf = gdf.dissolve()
        gdf = gdf.explode(index_parts=True).iloc[[0]]
        gdf4326 = gdf.to_crs(4326)
        _drop_z = lambda geom: wkb.loads(wkb.dumps(geom, output_dimension=2))
        gdf4326.geometry = gdf4326.geometry.transform(_drop_z) 
        """
        aoi_union = aoi.unary_union
        aoi_union_proj = gpd.GeoDataFrame(geometry=[aoi_union])
        # print(aoi_union_proj.geometry.transform)
        _drop_z = lambda geom: wkb.loads(wkb.dumps(geom, output_dimension=2))
        # aoi_union_proj.geometry = aoi_union_proj.geometry.transform(_drop_z)
        aoi_union_proj["geometry"] = aoi_union_proj["geometry"].apply(_drop_z)

        return aoi_union_proj.to_json()
    except Exception as e:
        raise e
    finally:
        remove_tree_file(upload_folder, session_id)

def isvalid(geom)-> int:
    try:
        shape(geom)
        return 1
    except:
        return 0

def process_kml_and_get_polygon(filepath, session_id, upload_folder):
    try:
        supported_drivers['kml'] = 'rw' # enable KML support which is disabled by default
        supported_drivers['KML'] = 'rw' # enable KML support which is disabled by default
        supported_drivers['libkml'] = 'rw' # enable KML support which is disabled by default
        supported_drivers['LIBKML'] = 'rw' # enable KML support which is disabled by default

        collection = list(fiona.open(filepath, 'r'))
        df = pd.DataFrame(collection)

        df["is_valid"] = df['geometry'].apply(lambda x: isvalid(x))
        df_valid = df[df['is_valid'] == 1]
        collection = json.loads(df_valid.to_json(orient='records'))

        gdf = gpd.GeoDataFrame.from_features(collection,crs=CRS('EPSG:4326'))

        #gdf = gpd.read_file(filepath)
        gdf = gdf.dissolve()
        gdf = gdf.explode(index_parts=False)

        gdf4326 = gdf.to_crs(4326)
        # _drop_z = lambda geom: wkb.loads(wkb.dumps(geom, output_dimension=2))
        # gdf4326.geometry = gdf4326.geometry.transform(_drop_z)

        _drop_z = lambda geom: wkb.loads(wkb.dumps(geom, output_dimension=2))
        # aoi_union_proj.geometry = aoi_union_proj.geometry.transform(_drop_z)
        gdf4326["geometry"] = gdf4326["geometry"].apply(_drop_z)

        return gdf4326.to_json()
    except Exception as e:
        raise e
    finally:
        remove_tree_file(upload_folder, session_id)

def process_kmz_and_get_polygon(filepath, session_id, upload_folder):
    temp_dir = 'temp_zip_extraction'
    extracted_filepath = os.path.join(upload_folder, session_id, temp_dir) # "Uploaded-File/"+session_id+"/"+temp_dir
    os.makedirs(extracted_filepath, exist_ok=True)

    try:
        with zipfile.ZipFile(filepath, 'r') as zip_file:
            zip_file.extractall(extracted_filepath)

        # check if ada file kml didalem zip, return error if not
        filename = None
        for root, dirs, files in os.walk(extracted_filepath):
            for file in files:
                if not file.startswith('.') and file.endswith('.kml'):
                    filename = os.path.join(root, file)
        if not filename:
            raise AppMessageException('No .kml file found in the ZIP file.')

        gdf4326 = process_kml_and_get_polygon(filename, session_id, upload_folder)

        return gdf4326
    except Exception as e:
        raise e
    finally:
        remove_tree_file(upload_folder, session_id)