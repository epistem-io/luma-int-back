"""Indonesian number and date formatting for the map report. Pure functions."""
from datetime import timedelta

MONTHS = ('Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli',
          'Agustus', 'September', 'Oktober', 'November', 'Desember')


def num(value, decimals=0):
    """4786.72 -> '4.787', (22.5, 1) -> '22,5'."""
    if value is None:
        return '–'
    text = '{:,.{d}f}'.format(float(value), d=decimals)
    return text.replace(',', ' ').replace('.', ',').replace(' ', '.')


def date_id(d):
    return '{} {} {}'.format(d.day, MONTHS[d.month - 1], d.year)


def date_range_id(start, end):
    if start.year == end.year:
        return '{} {} – {} {} {}'.format(start.day, MONTHS[start.month - 1],
                                         end.day, MONTHS[end.month - 1], end.year)
    return '{} – {}'.format(date_id(start), date_id(end))


def datetime_wib(utc_dt):
    local = utc_dt + timedelta(hours=7)
    return '{}, {:02d}.{:02d} WIB'.format(date_id(local), local.hour, local.minute)


def coord_id(lat, lon):
    return '{}° {}, {}° {}'.format(num(abs(lat), 2), 'LS' if lat < 0 else 'LU',
                                   num(abs(lon), 2), 'BT' if lon >= 0 else 'BB')


def hex_code(color):
    """'#efc6d5' -> 'EFC6D5' (pdf.py adds the hash back where it needs one)."""
    return (color or '').lstrip('#').upper()
