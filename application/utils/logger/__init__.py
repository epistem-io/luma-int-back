# application/utils/logger/__init__.py
from flask import g as g_var, current_app, render_template_string
from flask_login import current_user

def logging(response):
    '''
    logging api activity to the console
    '''

    if response.status_code == 200:
        g_var.__log_type__ = 'success'
    else:
        g_var.__log_type__ = 'failed'

    current_app.logger.info(
        'after_request - {} - logger - {} - {}: {}'.format(
            'no_user' if not current_user.is_authenticated else current_user.id,
            str(g_var.__api_name__),
            str(g_var.__log_type__),
            str(g_var.__api_description__)
        )
    )