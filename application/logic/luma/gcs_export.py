import os
import time
import uuid
from datetime import datetime, UTC, timedelta

import ee
import rasterio
from google.cloud import storage

GCS_BUCKET = os.environ.get('GCS_BUCKET_NAME', 'epistem-luma')
GCS_PREFIX = os.environ.get('GCS_BUCKET_PREFIX', 'dev')
POLL_INTERVAL = 15
EXPORT_TIMEOUT = 3600
TEMP_DIR = os.environ.get(
    'TEMP_DIR',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'temp_folder')
)


def write_author_metadata(filename, author):
    """Re-download GCS blob, update author tag, re-upload."""
    client = storage.Client()
    blob = client.bucket(GCS_BUCKET).blob(f'{GCS_PREFIX}/{filename}.tif')
    blob.reload()
    metadata = blob.metadata or {}
    metadata['author'] = author

    os.makedirs(TEMP_DIR, exist_ok=True)
    tmp_path = os.path.join(TEMP_DIR, f'{uuid.uuid4().hex}.tif')
    try:
        blob.download_to_filename(tmp_path)
        with rasterio.open(tmp_path, 'r+', IGNORE_COG_LAYOUT_BREAK='YES') as ds:
            ds.update_tags(author=author)
        blob.metadata = metadata
        blob.upload_from_filename(tmp_path, content_type='image/tiff')
        blob.patch()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    
    blob.make_public()


def export_to_gcs(image, filename, aoi, scale, crs='EPSG:4326', metadata={}):
    """Export EE image to GCS and return a public download URL."""
    if not GCS_BUCKET:
        raise Exception('GCS_BUCKET_NAME env var not set')

    now = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=7)
    metadata.update({
        'date': '{} WIB'.format(now.strftime('%Y-%m-%d %H:%M:%S')),
        'generated_using': 'Luma Geospatial Engine version v0.1.0',
    })
    image = image.set(metadata)

    task = ee.batch.Export.image.toCloudStorage(
        image=image,
        description=filename[:100],
        bucket=GCS_BUCKET,
        fileNamePrefix=f'{GCS_PREFIX}/{filename}',
        region=aoi,
        scale=scale,
        crs=crs,
        fileFormat='GeoTIFF',
        formatOptions={'cloudOptimized': True, 'noData': 0}
    )
    task.start()

    elapsed = 0
    while task.active() and elapsed < EXPORT_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    status = task.status()
    if status['state'] != 'COMPLETED':
        raise Exception('GCS export {}: {}'.format(
            status['state'], status.get('error_message', '')))

    client = storage.Client()
    blob = client.bucket(GCS_BUCKET).blob(f'{GCS_PREFIX}/{filename}.tif')
    blob.metadata = metadata
    blob.patch()

    os.makedirs(TEMP_DIR, exist_ok=True)
    tmp_path = os.path.join(TEMP_DIR, f'{uuid.uuid4().hex}.tif')
    try:
        blob.download_to_filename(tmp_path)
        with rasterio.open(tmp_path, 'r+', IGNORE_COG_LAYOUT_BREAK='YES') as ds:
            ds.update_tags(**metadata)
        blob.upload_from_filename(tmp_path, content_type='image/tiff')
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    blob.make_public()
    return blob.public_url
