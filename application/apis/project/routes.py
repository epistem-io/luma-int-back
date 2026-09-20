from application.apis.project import project_apis_blueprint
from flask import make_response, request, jsonify, g as g_var
from flask_login import current_user
from flask_cors import cross_origin

# logic
from application.logic.user import project as project_logic

# utils
from application.utils.common import AppMessageException, ErrorCodeEnum
from application.utils.common import app_exception_handler, success_handler


def _require_account():
    if not current_user.is_authenticated:
        raise AppMessageException('not authenticated', error=ErrorCodeEnum.ERR_NOAUTH)
    return current_user

def _json_body():
    data = request.get_json(silent=True) if request.is_json else None
    if not isinstance(data, dict):
        raise AppMessageException('invalid input: expected a JSON object', error=ErrorCodeEnum.ERR_VALIDATION)
    return data

def _handle(e):
    status = 401 if getattr(e, 'error', None) == ErrorCodeEnum.ERR_NOAUTH else (
        400 if isinstance(e, AppMessageException) else 500
    )
    return make_response(
        jsonify(app_exception_handler(e, services=g_var.__api_name__)), status
    )
    
@project_apis_blueprint.route('', methods=['POST'])
@cross_origin()
def create_project():
    g_var.__api_name__ = 'create_project'
    g_var.__api_description__ = 'create a named project'
    try:
        account = _require_account()
        if not request.is_json:
            raise AppMessageException('please provide json data', error=ErrorCodeEnum.ERR_VALIDATION)
        data = _json_body()
        known_project = project_logic.create_project(
            account.id,
            data.get('name'),
            data.get('session_id'),
            data.get('checkpoint'),
        )
        return make_response(jsonify(success_handler(known_project.to_json())), 200)
    except Exception as e:
        return _handle(e)
    
@project_apis_blueprint.route('', methods=['GET'])
@cross_origin()
def list_projects():
    g_var.__api_name__ = 'list_projects'
    g_var.__api_description__ = 'list my projects'
    try:
        account = _require_account()
        projects = project_logic.list_projects(account.id)
        return make_response(
            jsonify(success_handler({'projects': [p.to_summary_json() for p in projects]})),
            200,
        )
    except Exception as e:
        return _handle(e)
    
@project_apis_blueprint.route('/<string:project_id>', methods=['GET'])
@cross_origin()
def get_project(project_id):
    g_var.__api_name__ = 'get_project'
    g_var.__api_description__ = 'get one project with checkpoint'
    try:
        account = _require_account()
        known_project = project_logic.get_project(account.id, project_id)
        return make_response(jsonify(success_handler(known_project.to_json())), 200)
    except Exception as e:
        return _handle(e)

@project_apis_blueprint.route('/<string:project_id>', methods=['PUT'])
@cross_origin()
def update_project(project_id):
    g_var.__api_name__ = 'update_project'
    g_var.__api_description__ = 'update project checkpoint and/or name'
    try:
        account = _require_account()
        if not request.is_json:
            raise AppMessageException('please provide json data', error=ErrorCodeEnum.ERR_VALIDATION)
        data = _json_body()
        known_project = project_logic.update_project(
            account.id,
            project_id,
            name=data.get('name'),
            checkpoint=data.get('checkpoint'),
        )
        return make_response(jsonify(success_handler(known_project.to_json())), 200)
    except Exception as e:
        return _handle(e)

@project_apis_blueprint.route('/<string:project_id>', methods=['DELETE'])
@cross_origin()
def delete_project(project_id):
    g_var.__api_name__ = 'delete_project'
    g_var.__api_description__ = 'delete a project'
    try:
        account = _require_account()
        project_logic.delete_project(account.id, project_id)
        return make_response(jsonify(success_handler({'deleted': True})), 200)
    except Exception as e:
        return _handle(e)

@project_apis_blueprint.route('/<string:project_id>/share', methods=['POST'])
@cross_origin()
def share_project(project_id):
    g_var.__api_name__ = 'share_project'
    g_var.__api_description__ = 'fork a project to another user'
    try:
        account = _require_account()
        if not request.is_json:
            raise AppMessageException('please provide json data', error=ErrorCodeEnum.ERR_VALIDATION)
        data = _json_body()
        new_project = project_logic.share_project(
            account.id, project_id, data.get('email')
        )
        return make_response(
            jsonify(success_handler({'shared': True, 'recipient_project_id': new_project.id})),
            200,
        )
    except Exception as e:
        return _handle(e)