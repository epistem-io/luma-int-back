# application/feature_flags.py
"""
Runtime feature flags (read from environment / .env).

These exist so performance-related changes can be switched off without a code
rollback: set the variable to 0/false in .env and restart the backend.

  MOSAIC_FAST_PATH (default: 1)
      Master switch for the faster image-mosaic path:
        - AOI selected via Kabupaten/Kota is passed to Earth Engine as a
          server-side asset reference instead of re-uploading every vertex
        - only the tile layers the frontend actually shows are computed
          (see MOSAIC_LAYERS)
        - tile ids (getMapId) are requested in parallel
        - no Map.centerObject round-trip
        - the GeoTIFF download URL is NOT computed inline; the frontend asks
          for it lazily via GET /luma/image-mosaic/download-url
      With MOSAIC_FAST_PATH=0 the original behaviour is restored exactly.

  MOSAIC_LAYERS (default: the three layers the frontend renders)
      Comma-separated layer names to compute when MOSAIC_FAST_PATH is on.

  MOSAIC_PARALLEL_WORKERS (default: 4)
      Thread pool size for parallel getMapId calls (1 = sequential).
"""
import os

_TRUE = {'1', 'true', 'yes', 'on'}
_FALSE = {'0', 'false', 'no', 'off'}


def env_bool(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    raw = raw.strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    return default


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def env_list(name, default):
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return list(default)
    return [part.strip() for part in raw.split(',') if part.strip()]


DEFAULT_MOSAIC_LAYERS = [
    'Composite - True Color (RGB)',
    'Composite - False Color Infrared (NIR/Red/Green)',
    'Composite - Land/Water (NIR/SWIR1/RED)',
]


def mosaic_fast_path():
    return env_bool('MOSAIC_FAST_PATH', True)


def mosaic_layers():
    return env_list('MOSAIC_LAYERS', DEFAULT_MOSAIC_LAYERS)


def mosaic_parallel_workers():
    return max(1, env_int('MOSAIC_PARALLEL_WORKERS', 4))
