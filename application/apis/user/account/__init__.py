# application/apis/user/account/__init__.py
from flask import request
from flask_restx import Namespace, Resource, fields, reqparse
import werkzeug

api = Namespace('account', 'user account related endpoints.')

# base models
blank_model = api.model('BlankObject', {})
error_results_model = api.model('ErrorStatus', {
    'message': fields.String,
    'success': fields.Boolean,
})
blank_results_object_model = api.model('BlankResultsObject', {
    'data': fields.Nested(blank_model),
    'success': fields.Boolean,
})
blank_results_list_model = api.model('BlankResultsList', {
    'data': fields.List(fields.Nested(blank_model)),
    'total_records': fields.Integer,
})

login_parser = api.parser()
login_parser.add_argument('email', type=str, required=True, help="account email, sample: john_doe@mail.com", location="json")
login_parser.add_argument('password', type=str, required=True, help="account password, sample: P@ssw0rd", location="json")

account_model = api.model('Account', {
    'uid': fields.String,
    'email': fields.String,
})

@api.route('/login')
class Login(Resource):
    success_models = api.model('LoginResponse', {
        'api_key': fields.String,
        'api_key_expired': fields.DateTime(dt_format='rfc822'),
        'user': fields.Nested(account_model, skip_none=True),
    })

    @api.response(200, 'Success', model=success_models)
    @api.response(400, 'Bad Request', model=error_results_model)
    @api.response(401, 'Unauthorized, please provide api key', model=error_results_model)
    @api.response(500, 'Internal Server error, refer to the error code and messages status.', model=error_results_model)
    @api.doc(parser=login_parser)
    def post(self):
        pass
