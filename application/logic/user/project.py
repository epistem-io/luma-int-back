import logging

from application import db
from application.models.user import Project, Account
from application.logic.user import session as session_logic
from application.logic.user.account import AccountLogic
from application.logic.user.invite_rules import is_valid_email
from application.logic.user.project_rules import (
    normalize_email,
    validate_project_name,
    rewrite_checkpoint_session,
)
from application.utils.common import AppMessageException, ErrorCodeEnum

from sqlalchemy import func

def create_project(account_id, name, session_id, checkpoint):
    try:
        name = validate_project_name(name)
        checkpoint = rewrite_checkpoint_session(checkpoint, session_id)
    except ValueError as e:
        raise AppMessageException(str(e), error=ErrorCodeEnum.ERR_VALIDATION)
    
    session_logic.get_session(session_id, validate=True)
    
    known_project = Project(
        account_id=account_id,
        session_id=session_id,
        name=name,
        checkpoint=checkpoint,
    )
    db.session.add(known_project)
    db.session.commit()
    db.session.refresh(known_project)
    return known_project

def list_projects(account_id):
    return (
        Project.query.filter_by(account_id=account_id)
        .order_by(Project.modified_date.desc())
        .all()
    )
    
def get_project(account_id, project_id, validate=True):
    known_project = Project.query.filter_by(
        id=project_id, account_id=account_id
    ).first()
    if validate and not known_project:
        raise AppMessageException('project not found.', error=ErrorCodeEnum.ERR_VALIDATION)
    return known_project

def update_project(account_id, project_id, name=None, checkpoint=None):
    known_project = get_project(account_id, project_id)
    
    if name is not None:
        try:
            known_project.name = validate_project_name(name)
        except ValueError as e:
            raise AppMessageException(str(e), error=ErrorCodeEnum.ERR_VALIDATION)
        
    if checkpoint is not None:
        if not isinstance(checkpoint, dict):
            raise AppMessageException(
                'invalid input: checkpoint, expected an object',
                error=ErrorCodeEnum.ERR_VALIDATION,
            )
        known_project.checkpoint = rewrite_checkpoint_session(
            checkpoint, known_project.session_id
        )
        
    db.session.commit()
    db.session.refresh(known_project)
    return known_project

def delete_project(account_id, project_id):
    known_project = get_project(account_id, project_id)
    db.session.delete(known_project)
    db.session.commit()
    
def share_project(account_id, project_id, recipient_email):
    """Fork a project to `recipient_email`. Returns (new_project, invited):
    invited is True when the recipient still has to set a password."""
    known_project = get_project(account_id, project_id)

    email = normalize_email(recipient_email)
    if not email:
        raise AppMessageException('please input: email', error=ErrorCodeEnum.ERR_VALIDATION)
    if not is_valid_email(email):
        raise AppMessageException('invalid input format: email', error=ErrorCodeEnum.ERR_VALIDATION)

    # Emails are neither unique nor lower-cased in this table: prefer the
    # account that can actually log in, then the oldest, so the pick is stable.
    # nullslast: Postgres sorts NULL first under DESC, and legacy rows may
    # have is_active = NULL.
    recipient = (
        Account.query.filter(func.lower(Account.email) == email)
        .order_by(Account.is_active.desc().nullslast(), Account.created_date.asc())
        .first()
    )
    if recipient and recipient.id == account_id:
        raise AppMessageException(
            'cannot share a project with yourself.',
            error=ErrorCodeEnum.ERR_VALIDATION,
        )

    sender = Account.query.filter_by(id=account_id).first()
    sender_name = (sender.fullname or sender.email) if sender else 'A Luma user'
    invited = False

    # One transaction for the invited account + the whole fork.
    try:
        if not recipient:
            recipient = AccountLogic.create_invited_account(email, account_id)
            invited = True
        elif not recipient.is_active:
            AccountLogic.ensure_invite_token(recipient)
            invited = True

        new_session = session_logic.clone_session(
            known_project.session_id, account_id=recipient.id
        )
        
        checkpoint = known_project.checkpoint if isinstance(known_project.checkpoint, dict) else {}
        new_project = Project(
            account_id=recipient.id,
            session_id=new_session.id,
            name=known_project.name,
            checkpoint=rewrite_checkpoint_session(checkpoint, new_session.id),
            shared_from=known_project.id,
        )
        db.session.add(new_project)
        db.session.commit()
    except Exception:
        # Re-raise as-is: wrapping it as AppMessageException would turn a DB
        # failure into a 400 and send the raw SQL text to the client.
        db.session.rollback()
        raise

    db.session.refresh(new_project)

    # The share already succeeded; a mail failure must not undo or fail it.
    try:
        if invited:
            AccountLogic.send_invite_email(recipient, sender_name, known_project.name)
        else:
            AccountLogic.send_share_notification(recipient, sender_name, known_project.name)
    except Exception as e:
        logging.error('share email failed for project {}: {}'.format(new_project.id, str(e)))

    return new_project, invited