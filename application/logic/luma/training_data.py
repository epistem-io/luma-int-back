import geopandas as gpd

from application import db
from application.models.luma import LulcClass, TrainingData
from application.utils.common import AppMessageException

from shapely.geometry import shape, mapping
from geoalchemy2.shape import from_shape, to_shape


def process(known_session, input_data):
    if type(input_data) != list:
        raise AppMessageException('invalid input: training data must be list')

    if len(input_data) == 0:
        raise AppMessageException('invalid input: training data must not be empty')

    reference_set, reference_dict_id, reference_dict_name = get_current_class_scheme(known_session)
    
    records = []
    for d in input_data:
        class_id = d.get('class_id')
        geom = d.get('geometry')

        if class_id is None or not geom:
            raise AppMessageException('invalid input: training data must contain class_id and geom')
        
        if class_id not in reference_dict_id:
            raise AppMessageException('invalid input: class_id not found in reference class')
        
        geom = shape(geom)
        
        records.append({
            'session_id': known_session.id,
            'class_id': class_id,
            'class_name': reference_dict_id[class_id]['name'],
            'class_color': reference_dict_id[class_id]['color'],
            'geom': from_shape(geom, srid=4326)
        })

    db.session.bulk_insert_mappings(TrainingData, records)
    db.session.commit()

    # return TrainingData.get_by_session_id(known_session.id, to_json=True)
    return [{
        'class_id': n['class_id'],
        'class_name': n['class_name'],
        'class_color': n['class_color'],
        'geometry': mapping(to_shape(n['geom'])),
        'session_id': n['session_id']
    } for n in records]

def process_file(known_session, aoi, filepath):
    gdf = gpd.read_file(filepath)

    reference_set, reference_dict_id, reference_dict_name = get_current_class_scheme(known_session)

    target_field, confidence = find_lulc_column(gdf, reference_set)
    print(f"Identified Column: {target_field} ({confidence:.1%} match rate)")

    if confidence < 1.0:
        raise AppMessageException('not all of the class is match with the reference class')
    
    reference_dict_type = 'id'
    if reference_dict_name.get(gdf[target_field].iloc[0]):
        reference_dict_type = 'name'
    
    print(reference_dict_name)
    print(reference_dict_id)

    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    
    records = [
        {
            'session_id': known_session.id,
            'class_id': getattr(row, target_field) if reference_dict_type == 'id' else reference_dict_name[getattr(row, target_field)]['id'],
            'class_name': getattr(row, target_field) if reference_dict_type == 'name' else reference_dict_id[getattr(row, target_field)]['name'],
            'class_color': reference_dict_name[getattr(row, target_field)]['color'] if reference_dict_type == 'name' else reference_dict_id[getattr(row, target_field)]['color'],
            "geom": from_shape(row.geometry, srid=4326)
        }
        for row in gdf.itertuples()
    ]

    db.session.bulk_insert_mappings(TrainingData, records)
    db.session.commit()
    
    # return TrainingData.get_by_session_id(known_session.id, to_json=True)
    return [{
        'class_id': n['class_id'],
        'class_name': n['class_name'],
        'class_color': n['class_color'],
        'geometry': mapping(to_shape(n['geom'])),
        'session_id': n['session_id']
    } for n in records]


def get_current_class_scheme(known_session):
    lulc_table = db.session.query(
        LulcClass.class_id,
        LulcClass.class_name,
        LulcClass.class_color,
    ).filter_by(session_id=known_session.id).distinct().all()

    reference_set = []
    reference_dict_id = {}
    reference_dict_name = {}
    for cls in lulc_table:
        reference_set.append(str(cls.class_id).lower())
        reference_set.append(cls.class_name.lower())
        reference_dict_id[cls.class_id] = {
            'id': cls.class_id,
            'name': cls.class_name,
            'color': cls.class_color
        }
        reference_dict_name[cls.class_name] = {
            'id': cls.class_id,
            'name': cls.class_name,
            'color': cls.class_color
        }

    return reference_set, reference_dict_id, reference_dict_name


def find_lulc_column(gdf, reference_set):
    best_col = None
    highest_match_rate = 0.0
    potential_cols = [c for c in gdf.columns if c not in ['geometry', 'index']]

    for col in potential_cols:
        unique_vals = gdf[col].dropna().unique().astype(str)

        if len(unique_vals) == 0:
            continue

        matches = sum(1 for v in unique_vals if v.strip().lower() in reference_set)
        match_rate = matches / len(unique_vals)

        if match_rate > highest_match_rate:
            highest_match_rate = match_rate
            best_col = col

        if highest_match_rate == 1.0:
            break

    return best_col, highest_match_rate


def delete(known_session, commit=False):
    TrainingData.query.filter_by(session_id=known_session.id).delete()
    if commit:
        db.session.commit()