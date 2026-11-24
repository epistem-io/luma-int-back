# application/logic/luma/predictor_vis.py
"""
Default colour schemes for previewing predictors on the map. Free of Flask
and Earth Engine imports so it can be unit-tested by file path
(tests/test_predictor_vis.py).

A continuous predictor is stretched between its 2nd and 98th percentile over
the area of interest (read once from Earth Engine by predictor.preview), so
no range has to be tuned by hand. Aspect and landform are fixed.
"""
import math

PERCENTILES = [2, 98]

# Hex colours, low -> high, in the form Earth Engine takes them.
GROUP_PALETTES = {
    'vegetation': ['8c510a', 'd8b365', 'f6e8c3', 'd9f0d3', '7fbf7b', '1b7837'],
    'waterHumidity': ['f7fbff', 'c6dbef', '6baed6', '2171b5', '08306b'],
    'landBuiltUp': ['1a9850', 'd9ef8b', 'fee08b', 'fc8d59', 'd73027'],
    'terrain': ['0b6623', '9acd32', 'f5deb3', 'b8860b', '8b4513', 'ffffff'],
    'radar': ['000000', 'ffffff'],
    'distance': ['ffffcc', 'a1dab4', '41b6c4', '2c7fb8', '253494'],
    'other': ['000000', 'ffffff'],
}
ID_PALETTES = {
    'SLOPE': ['ffffff', 'fdae61', 'd7191c', '7f0000'],
    # cyclic: north is the same colour at 0 and 360
    'ASPECT': ['ff0000', 'ffff00', '00ff00', '00ffff', '0000ff', 'ff00ff', 'ff0000'],
}

# Used when the percentile request fails or a band has no spread.
FALLBACK_RANGES = {
    'ELEVATION': (0, 3000),
    'SLOPE': (0, 60),
    'VV': (-25, 0), 'VH': (-30, -5), 'VV_VH': (0, 15),
    'HH': (-25, 0), 'HV': (-30, -5), 'HV_HH': (0, 15),
}
TYPE_FALLBACK_RANGES = {
    'spectral': (-1, 1),
    'terrain': (0, 3000),
    'radar': (-25, 0),
    'distance': (0, 50000),
}
FIXED_RANGES = {'ASPECT': (0, 360)}

# CSP/ERGo/1_0/Global/ALOS_landforms class table (value, label, colour), as
# published in the Earth Engine data catalog.
LANDFORM_ID = 'LANDFORM'
LANDFORM_CLASSES = [
    (11, 'Peak/ridge (warm)', '141414'),
    (12, 'Peak/ridge', '383838'),
    (13, 'Peak/ridge (cool)', '808080'),
    (14, 'Mountain/divide', 'ebeb8f'),
    (15, 'Cliff', 'f7d311'),
    (21, 'Upper slope (warm)', 'aa0000'),
    (22, 'Upper slope', 'd89382'),
    (23, 'Upper slope (cool)', 'ddc9c9'),
    (24, 'Upper slope (flat)', 'dccdce'),
    (31, 'Lower slope (warm)', '1c6330'),
    (32, 'Lower slope', '68aa63'),
    (33, 'Lower slope (cool)', 'b5c98e'),
    (34, 'Lower slope (flat)', 'e1f0e5'),
    (41, 'Valley', 'a975ba'),
    (42, 'Valley (narrow)', '6f198c'),
]


def landform_remap():
    """(class values, 0..n-1) so each class lands on exactly one palette colour."""
    values = [value for value, _, _ in LANDFORM_CLASSES]
    return values, list(range(len(values)))


def _is_fixed(item):
    return item['id'] == LANDFORM_ID or item['id'] in FIXED_RANGES


def stretch_bands(selection):
    """Bands whose range has to be read from Earth Engine."""
    return [item['band'] for item in selection if not _is_fixed(item)]


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value):
    return float('%.4g' % value)


def build_style(item, stats):
    """
    item:  one entry of predictor_rules.selection_bands()
    stats: reduceRegion(percentile [2, 98]) result, keys '<band>_p2' / '<band>_p98'

    -> {'kind', 'min', 'max', 'palette', 'stretched'} and, for a class map,
       'classes': [{'value', 'label', 'color'}]
    """
    pid = item['id']
    if pid == LANDFORM_ID:
        return {
            'kind': 'classes',
            'min': 0,
            'max': len(LANDFORM_CLASSES) - 1,
            'palette': [colour for _, _, colour in LANDFORM_CLASSES],
            'stretched': False,
            'classes': [
                {'value': value, 'label': label, 'color': '#' + colour}
                for value, label, colour in LANDFORM_CLASSES
            ],
        }

    palette = ID_PALETTES.get(pid) or GROUP_PALETTES.get(item.get('group')) or GROUP_PALETTES['other']
    style = {'kind': 'continuous', 'palette': list(palette), 'stretched': False}

    if pid in FIXED_RANGES:
        style['min'], style['max'] = FIXED_RANGES[pid]
        return style

    low = _number((stats or {}).get('{}_p{}'.format(item['band'], PERCENTILES[0])))
    high = _number((stats or {}).get('{}_p{}'.format(item['band'], PERCENTILES[1])))
    if low is not None and high is not None and high > low:
        style['min'], style['max'] = _round(low), _round(high)
        style['stretched'] = True
    else:
        style['min'], style['max'] = FALLBACK_RANGES.get(pid) or TYPE_FALLBACK_RANGES.get(item.get('type'), (-1, 1))
    return style


def ee_params(style):
    """Visualisation parameters for ee.Image.getMapId()."""
    return {'min': style['min'], 'max': style['max'], 'palette': list(style['palette'])}


def public_style(style):
    """What the API returns for a layer: CSS colours, no internal flags."""
    public = {
        'kind': style['kind'],
        'min': style['min'],
        'max': style['max'],
        'palette': ['#' + colour for colour in style['palette']],
    }
    if 'classes' in style:
        public['classes'] = style['classes']
    return public
