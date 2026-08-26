# tests/test_regency_options.py
#
# Run with:  venv/Scripts/python -m unittest tests.test_regency_options
# (or `python -m pytest tests` if pytest is installed)
#
# The module under test is loaded by file path on purpose: importing the
# `application` package boots Flask + Earth Engine, which unit tests must not do.

import importlib.util
import os
import unittest

_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'application', 'logic', 'geos', 'regency_options.py',
)
_spec = importlib.util.spec_from_file_location('regency_options', _MODULE_PATH)
regency_options = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(regency_options)

build_regency_options = regency_options.build_regency_options
build_label = regency_options.build_label


class BuildRegencyOptionsTest(unittest.TestCase):

    def test_drops_blank_names_and_codes(self):
        rows = [
            ['', '', 'Maluku', 999],
            ['81.01', '', 'Maluku', 4],
            ['', 'Nameless', 'Maluku', 4],
            ['13.03', 'Sijunjung', 'Sumatera Barat', 4],
        ]
        options = build_regency_options(rows)
        self.assertEqual([o['code'] for o in options], ['13.03'])

    def test_collapses_duplicate_codes(self):
        rows = [
            ['74.07', 'Wakatobi', 'Sulawesi Tenggara', 4],
            ['74.07', 'Wakatobi', 'Sulawesi Tenggara', 4],
            ['74.07', 'Wakatobi', 'Sulawesi Tenggara', 4],
        ]
        options = build_regency_options(rows)
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]['code'], '74.07')

    def test_kabupaten_and_kota_labels(self):
        rows = [
            ['13.03', 'Sijunjung', 'Sumatera Barat', 4],
            ['13.73', 'Kota Sawahlunto', 'Sumatera Barat', 5],
        ]
        options = {o['code']: o for o in build_regency_options(rows)}
        self.assertEqual(options['13.03']['type'], 'kabupaten')
        self.assertEqual(options['13.03']['label'], 'Kabupaten Sijunjung')
        self.assertEqual(options['13.73']['type'], 'kota')
        self.assertEqual(options['13.73']['label'], 'Kota Sawahlunto')

    def test_kota_type_inferred_from_name_when_tipadm_unknown(self):
        rows = [['99.01', 'Kota Contoh', 'Prov', None]]
        options = build_regency_options(rows)
        self.assertEqual(options[0]['type'], 'kota')
        self.assertEqual(options[0]['label'], 'Kota Contoh')

    def test_sorted_by_province_then_label(self):
        rows = [
            ['32.73', 'Kota Bandung', 'Jawa Barat', 5],
            ['11.01', 'Simeulue', 'Aceh', 4],
            ['32.04', 'Bandung', 'Jawa Barat', 4],
        ]
        options = build_regency_options(rows)
        self.assertEqual(
            [o['label'] for o in options],
            ['Kabupaten Simeulue', 'Kabupaten Bandung', 'Kota Bandung'],
        )

    def test_short_or_empty_rows_are_ignored(self):
        self.assertEqual(build_regency_options(None), [])
        self.assertEqual(build_regency_options([[], ['13.03', 'Sijunjung']]), [])

    def test_build_label_never_double_prefixes(self):
        self.assertEqual(build_label('Kabupaten Bandung', 'kabupaten'), 'Kabupaten Bandung')
        self.assertEqual(build_label('Kota Bandung', 'kota'), 'Kota Bandung')
        self.assertEqual(build_label('Bandung', 'kota'), 'Kota Bandung')


if __name__ == '__main__':
    unittest.main()
