from flask import Flask, g as g_var, request
from flask import make_response, jsonify
from flask.wrappers import Response
from application.utils.logger import logging
from application.utils.common import AppMessageException, ErrorCodeEnum, app_exception_handler
from application.utils.common import ErrorCodeEnum
from werkzeug.exceptions import NotFound

import gc
import traceback

class AppExtensions(object):

    def __init__(self, app: Flask = None):
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app: Flask):

        @app.before_request
        def init_request():
            g_var.__print_list__ = []
            g_var.__error_stack__ = []
            g_var.__api_name__ = 'unknown'
            g_var.__api_description__ = 'unknown'
            g_var.__log_type__ = 'unknown'

        @app.after_request
        def after_request_callback(response):

            # if type(response) == Response and response.is_json:
            #     response.headers['Content-Type'] = '{}; {}'.format(response.headers['Content-Type'], 'charset=utf-8')

            if g_var.get('__api_name'):
                try:
                    logging(response)
                except Exception as e:
                    app.logger.warning('error in logging (after_request) - {}: {}'.format(g_var.__api_name__, str(e)))

            if g_var.__print_list__:
                app.logger.info('\n'.join(g_var.__print_list__))

            app.logger.info('garbage collected: {}'.format(gc.collect()))
            return response
        
        @app.errorhandler(AppMessageException)
        def app_message_exception_handler(e):
            if e.error == ErrorCodeEnum.ERR_NOAUTH:
                return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 401) # send unauthorized
            return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 400) # send bad request

        @app.errorhandler(Exception)
        def exception_handler(e):
            if type(e) == NotFound:
                return make_response(jsonify(app_exception_handler(AppMessageException('Resource not found', error=ErrorCodeEnum.ERR_NOT_FOUND), services=g_var.__api_name__)), 404)

            try:
                from application import db
                from application.models.user import ErrorLog

                request_data = {}
                if request.args:
                    request_data['params'] = request.args.to_dict()
                if request.is_json and request.get_json(silent=True):
                    request_data['body'] = request.get_json(silent=True)
                elif request.form:
                    request_data['body'] = request.form.to_dict()

                session_id = (
                    request.args.get('session_id')
                    or (request.get_json(silent=True) or {}).get('session_id')
                    or request.form.get('session_id')
                )

                db.session.rollback()
                error_log = ErrorLog()
                error_log.api_name = g_var.__api_name__
                error_log.session_id = session_id
                error_log.request_url = request.url
                error_log.request_method = request.method
                error_log.request_data = request_data if request_data else None
                error_log.trace = traceback.format_exc()
                db.session.add(error_log)
                db.session.commit()
            except Exception as log_err:
                app.logger.warning('failed to save error log: {}'.format(str(log_err)))

            return make_response(jsonify(app_exception_handler(e, services=g_var.__api_name__)), 500) # send internal error