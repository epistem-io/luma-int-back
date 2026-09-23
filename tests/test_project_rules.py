# tests/test_project_rules.py
#
# Run with:  venv/Scripts/python -m unittest tests.test_project_rules
#
# Loaded by file path on purpose: importing the `application` package
# boots Flask + Earth Engine, which unit tests must not do.

import importlib.util
import os
import unittest

_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'application', 'logic', 'user', 'project_rules.py',
)
_spec = importlib.util.spec_from_file_location('project_rules', _MODULE_PATH)
project_rules = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(project_rules)

normalize_email = project_rules.normalize_email
validate_project_name = project_rules.validate_project_name
rewrite_checkpoint_session = project_rules.rewrite_checkpoint_session


class NormalizeEmailTest(unittest.TestCase):
    def test_lowercases_and_trims(self):
        self.assertEqual(normalize_email('  User@Mail.COM '), 'user@mail.com')

    def test_none_becomes_empty(self):
        self.assertEqual(normalize_email(None), '')


class ValidateProjectNameTest(unittest.TestCase):
    def test_trims_valid_name(self):
        self.assertEqual(validate_project_name('  Jambi 2024 '), 'Jambi 2024')

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            validate_project_name('   ')

    def test_none_raises(self):
        with self.assertRaises(ValueError):
            validate_project_name(None)

    def test_over_256_chars_raises(self):
        with self.assertRaises(ValueError):
            validate_project_name('x' * 257)


class RewriteCheckpointSessionTest(unittest.TestCase):
    def test_rewrites_session_id_only(self):
        cp = {'sessionId': 'old', 'stepKey': 'yourMap', 'basicInfo': {'a': 1}}
        out = rewrite_checkpoint_session(cp, 'new')
        self.assertEqual(out['sessionId'], 'new')
        self.assertEqual(out['stepKey'], 'yourMap')
        self.assertEqual(out['basicInfo'], {'a': 1})

    def test_does_not_mutate_input(self):
        cp = {'sessionId': 'old'}
        rewrite_checkpoint_session(cp, 'new')
        self.assertEqual(cp['sessionId'], 'old')

    def test_non_dict_raises(self):
        with self.assertRaises(ValueError):
            rewrite_checkpoint_session(['not', 'a', 'dict'], 'new')
