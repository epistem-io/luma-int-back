# application/models/contact.py
from application import db
from application.utils.common import get_date, get_uuid


class ContactSubmission(db.Model):
    __tablename__ = 'contact_submission'

    id = db.Column(db.String(36), primary_key=True, default=get_uuid)
    full_name = db.Column(db.String(256), nullable=False)
    email = db.Column(db.String(256), nullable=False)
    phone_number = db.Column(db.String(50), nullable=True)
    company_name = db.Column(db.String(256), nullable=True)
    message = db.Column(db.Text, nullable=False)

    created_date = db.Column(db.DateTime, default=get_date)

    def to_json(self):
        return {
            'id': self.id,
            'full_name': self.full_name,
            'email': self.email,
            'phone_number': self.phone_number,
            'company_name': self.company_name,
            'message': self.message,
            'created_date': self.created_date.isoformat() if self.created_date else None,
        }
