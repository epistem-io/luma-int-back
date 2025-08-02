# application/models/master.py
from application import db
from application.utils.common import get_date, map_attr

class Settings(db.Model):
    __tablename__ = 'master_settings'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), unique=True, nullable=False)
    value = db.Column(db.String(1024), nullable=False)

    @classmethod
    def find_by_name(self, name):
        return self.query.filter_by(name=name).first()
    
    @staticmethod
    def get_settings(name, type_=str):
        return type_(Settings.find_by_name(name).value)