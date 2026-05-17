# application/logic/contact/contact.py
import os
import logging

from application import db
from application.models.contact import ContactSubmission
from application.models.master import Settings
from application.utils.common import render_html_template
from application.utils.mail import send_email

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'utils', '_templates')


class ContactLogic:

    @staticmethod
    def submit(full_name, email, phone_number, company_name, message):
        submission = ContactSubmission(
            full_name=full_name,
            email=email,
            phone_number=phone_number,
            company_name=company_name,
            message=message,
        )
        db.session.add(submission)
        db.session.commit()

        try:
            ContactLogic._send_email(submission)
        except Exception as e:
            logging.error('contact email send failed: {}'.format(str(e)))

        return submission.to_json()

    @staticmethod
    def _send_email(submission: ContactSubmission):
        setting = Settings.find_by_name('CONTACT_MAIL_RECIPIENTS')
        if not setting or not setting.value.strip():
            raise ValueError('contact mail recipients not configured in settings table')
        recipients = [r.strip() for r in setting.value.split(';') if r.strip()]

        subject = '[Epistem] New Inquiry from {} — {}'.format(
            submission.full_name,
            submission.company_name or 'Individual',
        )
        body = render_html_template(
            os.path.join(_TEMPLATE_DIR, 'contact_notification.html'),
            full_name=submission.full_name,
            email=submission.email,
            phone=submission.phone_number or '—',
            company=submission.company_name or '—',
            message=submission.message,
        )

        send_email(recipients, subject, body)
