# session.py
import ee
from application import db
from application.models.user import Session
from flask_login import current_user
from application.utils.common import AppMessageException, ErrorCodeEnum

def init_session(session_id):
    known_session = get_session(session_id)
    if not known_session:
        known_session = Session()
        
        if current_user.is_authenticated:
            known_session.account_id = current_user.id
        
        db.session.add(known_session)
        db.session.commit()
        db.session.refresh(known_session)
    
    return known_session

def get_session(session_id, validate=False):
    known_session = Session.query.filter_by(id=session_id).first()
    if validate and not known_session:
        raise AppMessageException('session not found.', error=ErrorCodeEnum.ERR_VALIDATION)
    return known_session

def _session_scoped_models():
    from application.models.geos import Aoi, Lulc
    from application.models.luma import Luma, Layers, LulcClass, TrainingData
    from application.models.user import GeeAsset
    return (Aoi, Lulc, Luma, Layers, LulcClass, TrainingData, GeeAsset)

def clone_session(session_id, account_id=None):
    get_session(session_id, validate=True)
    
    new_session = Session()
    new_session.account_id = account_id
    db.session.add(new_session)
    db.session.flush()
    
    skipped = ('id', 'session_id', 'created_date', 'modified_date')
    for model in _session_scoped_models():
        for row in model.query.filter_by(session_id=session_id).all():
            data = {
                column.name: getattr(row, column.name)
                for column in model.__table__.columns
                if column.name not in skipped
            }
            db.session.add(model(session_id=new_session.id, **data))

    db.session.flush()
    return new_session