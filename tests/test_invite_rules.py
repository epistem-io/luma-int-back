# tests/test_invite_rules.py
#
# Run with:  venv/Scripts/python -m unittest tests.test_invite_rules
#
# Loaded by file path on purpose: importing the `application` package
# boots Flask + Earth Engine, which unit tests must not do.

import importlib.util
import os
import unittest
from datetime import datetime, timedelta

_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'application', 'logic', 'user', 'invite_rules.py',
)
_spec = importlib.util.spec_from_file_location('invite_rules', _MODULE_PATH)
rules = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rules)

NOW = datetime(2026, 9, 21, 12, 0, 0)


class ConstantsTest(unittest.TestCase):
    def test_limits_match_the_spec(self):
        self.assertEqual(rules.SIGNUP_TOKEN_HOURS, 24)
        self.assertEqual(rules.INVITE_TOKEN_HOURS, 168)
        self.assertEqual(rules.LOGIN_CODE_SECONDS, 60)
        self.assertEqual(rules.MAX_INVITES_PER_DAY, 10)


class IsExpiredTest(unittest.TestCase):
    def test_none_is_expired(self):
        self.assertTrue(rules.is_expired(None, NOW))

    def test_past_is_expired(self):
        self.assertTrue(rules.is_expired(NOW - timedelta(seconds=1), NOW))

    def test_future_is_not_expired(self):
        self.assertFalse(rules.is_expired(NOW + timedelta(seconds=1), NOW))


class CanInviteTest(unittest.TestCase):
    def test_below_limit(self):
        self.assertTrue(rules.can_invite(9))

    def test_at_limit(self):
        self.assertFalse(rules.can_invite(10))


class IsValidEmailTest(unittest.TestCase):
    def test_accepts_plain_address(self):
        self.assertTrue(rules.is_valid_email('new@person.com'))

    def test_rejects_garbage(self):
        for value in ('', None, 'nope', 'a@b', 'a b@c.com', '@c.com'):
            self.assertFalse(rules.is_valid_email(value), value)


class ResolveFullnameTest(unittest.TestCase):
    def test_submitted_wins_and_is_trimmed(self):
        self.assertEqual(rules.resolve_fullname('Old', '  New Name '), 'New Name')

    def test_falls_back_to_existing(self):
        self.assertEqual(rules.resolve_fullname('Existing', None), 'Existing')
        self.assertEqual(rules.resolve_fullname('Existing', '   '), 'Existing')

    def test_both_empty_raises(self):
        with self.assertRaises(ValueError):
            rules.resolve_fullname(None, '  ')

    def test_too_long_raises(self):
        with self.assertRaises(ValueError):
            rules.resolve_fullname(None, 'x' * 257)


class CleanOptionalTest(unittest.TestCase):
    def test_blank_becomes_none(self):
        self.assertIsNone(rules.clean_optional(None))
        self.assertIsNone(rules.clean_optional('   '))

    def test_trims(self):
        self.assertEqual(rules.clean_optional('  WRI '), 'WRI')

    def test_too_long_raises(self):
        with self.assertRaises(ValueError):
            rules.clean_optional('x' * 257)
