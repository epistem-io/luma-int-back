# application/logic/user/invite_rules.py
#
# Pure rules for share invites and the one-time login code. No application
# imports on purpose: tests load this module by file path without booting Flask.
import re

SIGNUP_TOKEN_HOURS = 24
INVITE_TOKEN_HOURS = 168          # an invite is often read days later
LOGIN_CODE_SECONDS = 60           # only has to survive one redirect
MAX_INVITES_PER_DAY = 10          # new accounts one sender may create per 24 h
MAX_TEXT_LENGTH = 256

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def is_expired(expires, now):
    return expires is None or now > expires


def can_invite(invites_last_24h):
    return invites_last_24h < MAX_INVITES_PER_DAY


def is_valid_email(value):
    return bool(value) and bool(_EMAIL_RE.match(str(value)))


def resolve_fullname(existing, submitted):
    candidate = (submitted or '').strip() or (existing or '').strip()
    if not candidate:
        raise ValueError('please input: fullname (text mandatory)')
    if len(candidate) > MAX_TEXT_LENGTH:
        raise ValueError('invalid input: fullname, max %d characters' % MAX_TEXT_LENGTH)
    return candidate


def clean_optional(value):
    cleaned = (value or '').strip()
    if not cleaned:
        return None
    if len(cleaned) > MAX_TEXT_LENGTH:
        raise ValueError('invalid input: max %d characters' % MAX_TEXT_LENGTH)
    return cleaned
