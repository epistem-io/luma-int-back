import os

from application import db
from application.models.luma import ExportJob
from application.utils.common import render_html_template
from application.utils.mail import send_email

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'utils', '_templates')


def save_export_job(session_id, ee_image_serialized):
    ExportJob.query.filter_by(session_id=session_id).delete()
    job = ExportJob(session_id=session_id, ee_image_serialized=ee_image_serialized, status='ready')
    db.session.add(job)
    db.session.commit()
    db.session.refresh(job)
    return job


def get_export_job(session_id):
    return ExportJob.query.filter_by(session_id=session_id).order_by(ExportJob.created_date.desc()).first()


def update_export_job(job_id, **kwargs):
    ExportJob.query.filter_by(id=job_id).update(kwargs)
    db.session.commit()


def request_email(job_id, email):
    ExportJob.query.filter_by(id=job_id).update({'email_requested': True, 'requester_email': email})
    db.session.commit()


def send_download_link(to_email: str, download_url: str, session_id: str):
    body = render_html_template(
        os.path.join(_TEMPLATE_DIR, 'lulc_download.html'),
        download_url=download_url,
        session_id=session_id,
    )
    send_email(to_email, '[Epistem] Your LULC Map is Ready for Download', body)
