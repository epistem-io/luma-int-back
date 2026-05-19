# worker_export.py — run standalone: python worker_export.py
import os
import signal
import sys

import ee
import google.auth
import geopandas as gpd
from google.cloud import pubsub_v1

from application import create_app, db

# create app and push context before importing anything that touches current_app
app = create_app()
app.app_context().push()

from application.models.luma import ExportJob, Luma
from application.models.user import Session, Account
from application.logic.luma.gcs_export import export_to_gcs, write_author_metadata
from application.logic.luma import export_job as export_job_logic
from application.logic.geos import aoi as aoi_logic

_, _PROJECT_ID = google.auth.default()
PUBSUB_SUBSCRIPTION_EXPORT = os.environ.get('PUBSUB_SUBSCRIPTION_EXPORT', 'luma-export-jobs-sub')


def _build_metadata(luma, session, train_gdf):
    author = session.account.fullname if session.account_id else '-'
    try:
        counts = train_gdf.groupby(['class_id', 'class_name']).size().sort_index()
        classes_str = ', '.join(
            '{} ({})'.format(name, n) for (_, name), n in counts.items()
        )
    except Exception:
        classes_str = '-'

    predictor_config = luma.predictor_config or {}
    if luma.use_predictor:
        parts = []
        individual = predictor_config.get('individual_predictors', {})
        if individual.get('elevation'):
            parts.append('Elevation')
        if individual.get('slope'):
            parts.append('Slope')
        if individual.get('aspect'):
            parts.append('Aspect')
        if individual.get('spectral_indices'):
            parts += individual.get('spectral_indices')
        predictor_str = ', '.join(parts) if parts else 'Not Used'
    else:
        predictor_str = 'Not Used'

    start_date = luma.start_date.strftime('%Y-%m-%d')
    end_date = luma.end_date.strftime('%Y-%m-%d')
    user_input = (
        'Spatial resolution: {sr}m x {sr}m; '
        'Satellite imagery date range: {sd} - {ed}; '
        'Satellite imagery source: {sensor}; '
        'Maximum cloudy area: {cc}%; '
        'Classes and data sample: {classes}; '
        'Predictor: {predictor}; '
        'Number of trees: {ntrees}; '
        'Minimum leaf population: {min_leaf}'
    ).format(
        sr=luma.spatial_resolution,
        sd=start_date,
        ed=end_date,
        sensor=luma.landsat_version,
        cc=luma.cloud_cover,
        classes=classes_str,
        predictor=predictor_str,
        ntrees=luma.ntrees,
        min_leaf=luma.min_leaf,
    )
    return {'author': author, 'user_input': user_input}


def handle_message(message):
    job_id = message.data.decode()
    with app.app_context():
        job = ExportJob.query.get(job_id)
        if not job:
            print('worker: job {} not found, skipping'.format(job_id))
            message.ack()
            return

        export_job_logic.update_export_job(job_id, status='pending')

        try:
            session = Session.query.get(job.session_id)
            luma = Luma.query.filter_by(session_id=job.session_id).first()
            _, aoi = aoi_logic.get_ee_aoi(job.session_id)

            train_gdf = gpd.read_postgis(
                db.text(
                    'select class_id, class_name, geom geometry '
                    'from luma_training_data where session_id = :sid order by class_id'
                ),
                db.engine,
                geom_col='geometry',
                params={'sid': job.session_id},
            )

            image = ee.deserializer.decode(job.ee_image_serialized)
            metadata = _build_metadata(luma, session, train_gdf)

            start_date = luma.start_date.strftime('%Y-%m-%d')
            end_date = luma.end_date.strftime('%Y-%m-%d')
            filename = '{session_id}_LULC_{sensor}_{start_date}_{end_date}'.format(
                session_id=job.session_id,
                sensor=luma.landsat_version,
                start_date=start_date,
                end_date=end_date,
            )

            download_url = export_to_gcs(image, filename, aoi, luma.spatial_resolution, metadata=metadata)

            # re-fetch to pick up any email_requested flag set during export
            db.session.refresh(job)
            # job = ExportJob.query.get(job_id)
            if job.email_requested and job.requester_email:
                requester = Account.query.filter_by(email=job.requester_email).first()
                if requester:
                    write_author_metadata(filename, requester.fullname or job.requester_email)
                export_job_logic.send_download_link(job.requester_email, download_url, job.session_id)

            export_job_logic.update_export_job(job_id, status='done', download_url=download_url)
            print('worker: job {} done — {}'.format(job_id, download_url))

        except Exception as e:
            print('worker: job {} failed — {}'.format(job_id, e))
            export_job_logic.update_export_job(job_id, status='failed', error_message=str(e))

    message.ack()


def main():
    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(_PROJECT_ID, PUBSUB_SUBSCRIPTION_EXPORT)
    streaming_pull = subscriber.subscribe(subscription_path, callback=handle_message)
    print('worker: listening on {}'.format(subscription_path))

    def shutdown(sig, frame):
        streaming_pull.cancel()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    streaming_pull.result()


if __name__ == '__main__':
    main()
