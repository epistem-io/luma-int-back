import os
import time
from datetime import datetime

import ee
from google.cloud import storage

GCS_BUCKET = os.environ.get('LUMA_GCS_BUCKET', '')
POLL_INTERVAL = 15
EXPORT_TIMEOUT = 3600


def export_to_gcs(image, filename, aoi, scale, crs='EPSG:4326'):
    """Export EE image to GCS and return a public download URL."""
    if not GCS_BUCKET:
        raise Exception('LUMA_GCS_BUCKET env var not set')

    now = datetime.now()
    image = image.set({
        'generated_by': 'LUMA',
        'generation_datetime': now.strftime('%Y-%m-%d %H:%M:%S'),
    })

    task = ee.batch.Export.image.toCloudStorage(
        image=image,
        description=filename[:100],
        bucket=GCS_BUCKET,
        fileNamePrefix=filename,
        region=aoi,
        scale=scale,
        crs=crs,
        fileFormat='GeoTIFF',
        formatOptions={'cloudOptimized': True}
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
    blob = client.bucket(GCS_BUCKET).blob('{}.tif'.format(filename))
    blob.make_public()
    return blob.public_url
