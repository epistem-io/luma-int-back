# application/logic/geos/regency_options.py
"""
Pure helpers for turning rows of the Indonesian regency GEE asset into
option dicts for the frontend. Kept free of Flask / Earth Engine imports so it
can be unit-tested in isolation.

Asset: projects/ee-rg2icraf/assets/Indonesian_Regency_Area
  KDPKAB  - BPS regency code (unique key, e.g. "13.73")
  WADMKK  - regency / city name ("Kota ..." already prefixed for cities)
  WADMPR  - province name
  TIPADM  - 4 = Kabupaten, 5 = Kota (anything else is a placeholder row)
"""

REGENCY_TYPE_KABUPATEN = 'kabupaten'
REGENCY_TYPE_KOTA = 'kota'

_TIPADM_TO_TYPE = {
    4: REGENCY_TYPE_KABUPATEN,
    5: REGENCY_TYPE_KOTA,
}


def _clean(value):
    return (value or '').strip() if isinstance(value, str) else ('' if value is None else str(value).strip())


def _regency_type(name, tipadm):
    """Resolve kabupaten/kota, falling back to the name prefix when TIPADM is unusual."""
    try:
        tipadm_int = int(tipadm)
    except (TypeError, ValueError):
        tipadm_int = None

    if tipadm_int in _TIPADM_TO_TYPE:
        return _TIPADM_TO_TYPE[tipadm_int]

    lowered = name.lower()
    if lowered.startswith('kota '):
        return REGENCY_TYPE_KOTA
    return REGENCY_TYPE_KABUPATEN


def build_label(name, regency_type):
    """Human readable label: 'Kabupaten X' / 'Kota X' (never double-prefixed)."""
    lowered = name.lower()
    if lowered.startswith('kabupaten ') or lowered.startswith('kota '):
        return name
    prefix = 'Kota' if regency_type == REGENCY_TYPE_KOTA else 'Kabupaten'
    return '{} {}'.format(prefix, name)


def build_regency_options(rows):
    """
    Args:
        rows: iterable of [code, name, province, tipadm] (order matters — it
              matches the reduceColumns selector used in regency.py).

    Returns:
        list of dicts {code, name, type, province, label} sorted by province
        then label; blank names dropped; duplicate codes collapsed.
    """
    by_code = {}

    for row in rows or []:
        if not row or len(row) < 4:
            continue
        code, name, province, tipadm = row[0], row[1], row[2], row[3]

        code = _clean(code)
        name = _clean(name)
        province = _clean(province)

        if not name or not code:
            continue

        if code in by_code:
            continue

        regency_type = _regency_type(name, tipadm)

        by_code[code] = {
            'code': code,
            'name': name,
            'type': regency_type,
            'province': province,
            'label': build_label(name, regency_type),
        }

    return sorted(by_code.values(), key=lambda o: (o['province'].lower(), o['label'].lower()))
