# session.py
import ee
from application import db
from application.models.user import Session
from flask_login import current_user

def init_session(session_id):
    known_session = Session.query.filter_by(id=session_id).first()
    if not known_session:
        known_session = Session()
        
        if current_user.is_authenticated:
            known_session.account_id = current_user.id
        
        db.session.add(known_session)
        db.session.flush()
        db.session.refresh(known_session)
    
    return known_session
    