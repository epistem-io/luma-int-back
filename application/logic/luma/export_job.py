import os
from html import escape

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


_SHARE_EMAIL_COPY = {
    'en': {
        'subject': 'Luma mapping results have been shared with you',
        'header_subtitle': 'Shared Mapping Results',
        'greeting': 'Hello {recipient},',
        'intro': '{sender} has shared the following mapping results with you via Luma.',
        'cta_hint': 'Click the button below to view the results:',
        'button_label': 'View Results',
        'fallback_hint': "If the button doesn't work, copy and paste this link into your browser:",
        'footer_note': 'You received this email because someone shared their Luma mapping results with you.',
    },
    'id': {
        'subject': 'Hasil pemetaan Luma telah dibagikan kepada Anda',
        'header_subtitle': 'Hasil Pemetaan Dibagikan',
        'greeting': 'Halo {recipient},',
        'intro': '{sender} membagikan hasil pemetaan berikut melalui Luma:',
        'cta_hint': 'Klik tombol di bawah untuk melihat hasilnya:',
        'button_label': 'Buka Hasil',
        'fallback_hint': 'Jika tombol tidak berfungsi, salin dan tempel tautan ini ke peramban Anda:',
        'footer_note': 'Anda menerima email ini karena seseorang membagikan hasil pemetaan Luma kepada Anda.',
    },
}


def send_share_link(to_email: str, recipient_name: str, sender_name: str, view_url: str, language: str = 'id'):
    copy = _SHARE_EMAIL_COPY.get(language, _SHARE_EMAIL_COPY['id'])
    body = render_html_template(
        os.path.join(_TEMPLATE_DIR, 'lulc_share.html'),
        header_subtitle=copy['header_subtitle'],
        greeting=copy['greeting'].format(recipient=escape(recipient_name)),
        intro=copy['intro'].format(sender=escape(sender_name)),
        cta_hint=copy['cta_hint'],
        button_label=copy['button_label'],
        fallback_hint=copy['fallback_hint'],
        footer_note=copy['footer_note'],
        view_url=view_url,
    )
    send_email(to_email, copy['subject'], body)
