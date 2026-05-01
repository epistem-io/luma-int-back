# application/apis/contact/routes.py
import re
from flask import make_response, request, jsonify, g as g_var
from flask_cors import cross_origin

from application.apis.contact import contact_apis_blueprint
from application.logic.contact.contact import ContactLogic
from application.utils.common import AppMessageException, ErrorCodeEnum, success_handler


@contact_apis_blueprint.route('/submit', methods=['POST'])
@cross_origin()
def contact_submit():
    g_var.__api_name__ = 'contact_submit'
    g_var.__api_description__ = 'contact us form submission'

    if not request.is_json:
        raise AppMessageException('invalid input: request must be json', error=ErrorCodeEnum.ERR_VALIDATION)

    data = request.get_json()

    full_name = data.get('full_name')
    email = data.get('email')
    phone_number = data.get('phone_number')
    company_name = data.get('company_name')
    message = data.get('message')

    if not full_name:
        raise AppMessageException('please input: full_name', error=ErrorCodeEnum.ERR_VALIDATION)
    if not email:
        raise AppMessageException('please input: email', error=ErrorCodeEnum.ERR_VALIDATION)
    if not re.match(r'[^@]+@[^@]+\.[^@]+', email):
        raise AppMessageException('invalid input format: email', error=ErrorCodeEnum.ERR_VALIDATION)
    if not message:
        raise AppMessageException('please input: message', error=ErrorCodeEnum.ERR_VALIDATION)

    result = ContactLogic.submit(
        full_name=full_name,
        email=email,
        phone_number=phone_number,
        company_name=company_name,
        message=message,
    )

    return make_response(jsonify(success_handler(result)), 200)
