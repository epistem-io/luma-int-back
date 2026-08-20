# aoi.py
import ee
from application import db
from application.models.geos import Aoi
from application.models.master import Settings

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

from application.utils.common import AppMessageException, remove_tree_file, ErrorCodeEnum
from application.feature_flags import mosaic_fast_path

import logging

from luma_ge.input_utils import shapefile_validator, EE_converter

validate = shapefile_validator(verbose=True)
converter = EE_converter(verbose=True)

def aoi(known_session, geometry):
    geometry = ee.Geometry(geometry)

    geojson = geometry.getInfo()
    area_size = geometry.area().getInfo()

    return save_aoi(known_session, geojson, area_size)


def save_aoi(known_session, geojson_geometry, area_size_m2, regency_code=None):
    """
    Upsert the session AOI from an already-resolved GeoJSON geometry and its
    area in square metres (no Earth Engine round-trip). Used by `aoi()` and by
    callers that already computed geometry+area server-side (e.g. regency).

    `regency_code` (KDPKAB) is stored when the AOI came from the Kabupaten/Kota
    picker so later steps can reference the GEE asset server-side; it is reset
    to None for drawn/uploaded AOIs.
    """
    shapely_geom = shape(geojson_geometry)
    wkt_geom = shapely_to_wkt(shapely_geom)

    known_aoi = Aoi.query.filter_by(session_id=known_session.id).first()
    if not known_aoi:
        known_aoi = Aoi()
        known_aoi.session_id = known_session.id

    known_aoi.geom = wkt_geom
    known_aoi.area_size = (area_size_m2 / 10000) if area_size_m2 else 0
    known_aoi.regency_code = regency_code or None

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
            raise AppMessageException('No .shp file found in the ZIP file.', error=ErrorCodeEnum.ERR_VALIDATION)

        # check if crs epsg != 4326 return error
        aoi = gpd.read_file(filename)
        # aoi = aoi.to_crs(4326)
        # """ 
        # gdf = gpd.read_file(filename)
        # gdf = gdf.dissolve()
        # gdf = gdf.explode(index_parts=True).iloc[[0]]
        # gdf4326 = gdf.to_crs(4326)
        # _drop_z = lambda geom: wkb.loads(wkb.dumps(geom, output_dimension=2))
        # gdf4326.geometry = gdf4326.geometry.transform(_drop_z) 
        # """
        # aoi_union = aoi.unary_union
        # aoi_union_proj = gpd.GeoDataFrame(geometry=[aoi_union])
        # # print(aoi_union_proj.geometry.transform)
        # _drop_z = lambda geom: wkb.loads(wkb.dumps(geom, output_dimension=2))
        # # aoi_union_proj.geometry = aoi_union_proj.geometry.transform(_drop_z)
        # aoi_union_proj["geometry"] = aoi_union_proj["geometry"].apply(_drop_z)

        gdf_cleaned = validate.validate_and_fix_geometry(aoi)
        if gdf_cleaned is None:
            raise AppMessageException('Validasi geometri gagal.', error=ErrorCodeEnum.ERR_VALIDATION)
        
        # aoi = converter.convert_aoi_gdf(gdf_cleaned)
        # if aoi is None:
        #     raise AppMessageException('Gagal memuat wilayah kajian ke server', error=ErrorCodeEnum.ERR_VALIDATION)

        # Drop Z coordinates — EE rejects 3D geometries
        _drop_z = lambda geom: wkb.loads(wkb.dumps(geom, output_dimension=2))
        gdf_cleaned["geometry"] = gdf_cleaned["geometry"].apply(_drop_z)

        # Dissolve multiple features into one AOI polygon
        gdf_cleaned = gdf_cleaned.dissolve()

        return gdf_cleaned.to_json()
        # return aoi_union_proj.to_json()
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
            raise AppMessageException('No .kml file found in the ZIP file.', error=ErrorCodeEnum.ERR_VALIDATION)

        gdf4326 = process_kml_and_get_polygon(filename, session_id, upload_folder)

        return gdf4326
    except Exception as e:
        raise e
    finally:
        remove_tree_file(upload_folder, session_id)

def get_ee_aoi(session_id):
    known_aoi = Aoi.query.filter_by(session_id=session_id).first()
    if not known_aoi:
        raise AppMessageException('aoi not found', error=ErrorCodeEnum.ERR_VALIDATION)
    
    max_draw_area = Settings.get_settings('MAX_DRAW_AREA')
    if known_aoi.area_size > int(max_draw_area):
        raise AppMessageException('draw area exceeds maximum limit', error=ErrorCodeEnum.ERR_VALIDATION)

    aoi = None

    # Fast path: a Kabupaten/Kota AOI can be expressed as a server-side
    # reference to the GEE asset. This avoids re-sending every vertex of the
    # (often huge, multi-island) polygon on every Earth Engine call, which was
    # measured at ~20 s per call for large regencies. Disable with
    # MOSAIC_FAST_PATH=0 to always use the stored geometry.
    if known_aoi.regency_code and mosaic_fast_path():
        try:
            from application.logic.geos import regency as regency_logic
            aoi = regency_logic.get_regency_ee_geometry(known_aoi.regency_code)
        except Exception as e:
            logging.warning('get_ee_aoi: regency reference failed for %s, falling back to stored geometry: %s',
                            known_aoi.regency_code, e)
            aoi = None

    if aoi is None:
        aoi = wkb_to_ee_geometry(str(known_aoi.geom))

    return known_aoi, aoi