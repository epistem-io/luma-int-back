MAX_PROJECT_NAME_LENGTH = 256

def normalize_email(value):
    if not value:
        return ''
    return str(value).strip().lower()

def validate_project_name(name):
    if not name or not str(name).strip():
        raise ValueError('please input: project name')
    trimmed = str(name).strip()
    if len(trimmed) > MAX_PROJECT_NAME_LENGTH:
        raise ValueError(
            'invalid input: project name, max %d characters' % MAX_PROJECT_NAME_LENGTH
        )
    return trimmed

def rewrite_checkpoint_session(checkpoint, new_session_id):
    if not isinstance(checkpoint, dict):
        raise ValueError('invalid input: checkpoint, expected an object')
    out = dict(checkpoint)
    out['sessionId'] = new_session_id
    return out