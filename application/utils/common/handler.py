# application/utils/handler.py
from flask import current_app, g as g_var
import sys
import logging
from sqlalchemy import exc
import gc

logging.basicConfig(
    stream=sys.stdout, 
    level=logging.DEBUG,
    format='%(asctime)s - %(process)d - %(levelname)s - %(message)s',
)
env = current_app.config.get('ENV')

def eprint(*args, **kwargs):
    logging.error(*args)

class ErrorCodeEnum:
    ERR_VALIDATION = { 'code': 'ERR_VALIDATION', 'message': 'Invalid input data' }
    ERR_UNAUTHORIZED = { 'code': 'ERR_UNAUTHORIZED', 'message': 'Unauthorized' }
    ERR_FORBIDDEN = { 'code': 'ERR_FORBIDDEN', 'message': 'Forbidden' }
    ERR_NOT_FOUND = { 'code': 'ERR_NOT_FOUND', 'message': 'Resource not found' }
    ERR_INTERNAL = { 'code': 'ERR_INTERNAL', 'message': 'Internal server error' }
    ERR_NOAUTH = { 'code': 'ERR_NOAUTH', 'message': 'Not authenticated' }

class ErrorStack:
    def __init__(self, message='', field='', row=None):
        self.message = message
        self.field = field
        self.row = row

    def _asdict(self):
        return {
            'message': self.message,
            'field': self.field,
            'row': self.row
        }

class AppMessageException(Exception):
    
    def __init__(self, message="", error=ErrorCodeEnum.ERR_VALIDATION):
        self.error = error

def app_exception_handler(e, default_data={}, services='defaultservices'):
    eprint('{}: {}'.format(services, str(e)))

    context = {
        'error': ErrorCodeEnum.ERR_INTERNAL if not g_var.__error_stack__ else ErrorCodeEnum.ERR_VALIDATION, # error stack cuma diisi manual, jadi kalau ada isinya pasti validation
        'stack': [n._asdict() for n in g_var.__error_stack__],
        'trace': str(e),
        'success': False
    }

    try:
        raise e
    except AppMessageException: # handle app message
        context['error'] = e.error
    except exc.SQLAlchemyError: # handle error db
        if env != 'development':
            context['trace'] = 'something went wrong on our side - 0'
    except:
        if env != 'development':
            context['trace'] = 'something went wrong on our side - 1'

    gc.collect()

    return context

def success_handler(results:dict=None, status_code:int=None, message:str=None):
    context = {}
    if not results and type(results) == list:
        context = []
    if results:
        context = results
    if message:
        context['message'] = message
    if status_code:
        context['status_code'] = status_code

    gc.collect()

    return context