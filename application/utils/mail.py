# application/utils/mail.py
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app


def send_email(to: list[str] | str, subject: str, html_body: str) -> None:
    smtp_host = current_app.config['MAIL_SMTP_HOST']
    smtp_port = current_app.config['MAIL_SMTP_PORT']
    sender = current_app.config['MAIL_SENDER']
    password = current_app.config['MAIL_PASSWORD']

    recipients = [to] if isinstance(to, str) else to

    msg = MIMEMultipart('alternative')
    msg['From'] = sender
    msg['To'] = ', '.join(recipients)
    msg['Subject'] = subject
    msg.attach(MIMEText(html_body, 'html'))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())
