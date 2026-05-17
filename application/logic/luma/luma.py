from application.models.luma import Luma
from application import db

from application.utils.common import AppMessageException

def save_param(
    known_session,
    start_date:str,
    end_date:str,
    landsat_version:str = 'L8_SR',
    cloud_cover:int = 30,
    spatial_resolution:int = 30
):
    
    known_luma = Luma.query.filter_by(session_id=known_session.id).first()
    if not known_luma:
        known_luma = Luma(
            session_id=known_session.id,
            start_date=start_date,
            end_date=end_date,
            landsat_version=landsat_version,
            cloud_cover=cloud_cover,
            spatial_resolution=spatial_resolution,
            ntrees=300,
            min_leaf=2,
            use_predictor=False
        )
        db.session.add(known_luma)
        db.session.commit()
    
    return known_luma


def get(known_session, validate=False):
    known_luma = Luma.query.filter_by(session_id=known_session.id).first()
    if not known_luma and validate:
        raise AppMessageException('luma params data (step-1) not found')
    return known_luma

    


