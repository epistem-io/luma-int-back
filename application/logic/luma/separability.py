import geopandas as gpd

from application import db
from application.logic.geos.aoi import converter
from application.logic.luma.composite import build_composite
from application.logic.luma.separability_summary import build_summary

from luma_ge.sample_data_quality import sample_quality

MAX_PIXELS_PER_CLASS = 5000

def analyze(known_session, aoi, luma):
    session_id = known_session.id
    
    train_gdf = gpd.read_postgis(
        db.text(
        '''
        select
            class_id,
            class_name,
            class_color,
            geom geometry
        from luma_training_data
        where session_id = :session_id
        order by class_id
        '''
        ),
        db.engine,
        geom_col='geometry',
        params={'session_id': session_id}
    )
    
    if train_gdf.empty or train_gdf['class_id'].nunique() < 2:
        return None
    
    image = build_composite(
        aoi=aoi,
        start_date=luma.start_date.strftime('%Y-%m-%d'),
        end_date=luma.end_date.strftime('%Y-%m-%d'),
        landsat_version=luma.landsat_version,
        cloud_cover=luma.cloud_cover,
    )
    if image is None:
        return None
    
    roi_ee = converter.convert_roi_gdf(train_gdf)
    
    analyzer = sample_quality(
        training_data=roi_ee,
        image=image,
        class_property='class_id',
        region=aoi,
        class_name_property='class_name',
    )
    
    pixel_extract = analyzer.extract_spectral_values(
        scale=luma.spatial_resolution,
        max_pixels_per_class=MAX_PIXELS_PER_CLASS
    )
    sep_df = analyzer.get_separability_df(pixel_extract, method='TD')

    uploaded_classes = [
        {'class_id': int(row.class_id), 'class_name': str(row.class_name)}
        for row in train_gdf[['class_id', 'class_name']].drop_duplicates().itertuples(index=False)
    ]

    pixel_counts = {}
    if not pixel_extract.empty and 'class_id' in pixel_extract.columns:
        pixel_counts = {
            int(class_id): int(count)
            for class_id, count in pixel_extract.groupby('class_id').size().items()
        }

    return build_summary(uploaded_classes, pixel_counts, sep_df)