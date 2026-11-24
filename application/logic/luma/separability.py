import geopandas as gpd

from application import db
from application.logic.geos.aoi import converter
from application.logic.luma import predictor as predictor_logic
from application.logic.luma.composite import build_composite
from application.logic.luma.separability_summary import build_summary, build_comparison

from luma_ge.sample_data_quality import sample_quality

MAX_PIXELS_PER_CLASS = 5000


def training_gdf(session_id):
    """The session's training data as a GeoDataFrame (class_id, class_name, class_color, geometry)."""
    return gpd.read_postgis(
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


def _extract(train_gdf, image, aoi, scale, max_pixels_per_class):
    """
    Sample the image at the training data.
    -> (analyzer, pixel_extract, uploaded_classes, pixel_counts)
    """
    roi_ee = converter.convert_roi_gdf(train_gdf)

    analyzer = sample_quality(
        training_data=roi_ee,
        image=image,
        class_property='class_id',
        region=aoi,
        class_name_property='class_name',
    )

    pixel_extract = analyzer.extract_spectral_values(
        scale=scale,
        max_pixels_per_class=max_pixels_per_class
    )

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

    return analyzer, pixel_extract, uploaded_classes, pixel_counts


def analyze(known_session, aoi, luma, scale=None, max_pixels_per_class=None):
    """Summary only: what the separability endpoint returns."""
    detail = analyze_detailed(known_session, aoi, luma, scale=scale, max_pixels_per_class=max_pixels_per_class)
    return detail['summary'] if detail else None


def analyze_detailed(known_session, aoi, luma, scale=None, max_pixels_per_class=None):
    """
    Run the class separability analysis for a session's training points.
    Returns {'summary', 'pixel_counts': {class_id: valid pixels},
    'pairs': [{a, b, td}] lowest TD first}, or None when it cannot be computed.

    Args:
        scale: sampling scale in metres; defaults to the session's
            spatial resolution.
        max_pixels_per_class: per-class random pixel cap; defaults to
            MAX_PIXELS_PER_CLASS. (Same tunables as LumaLite Module 4.)
    """
    scale = scale or luma.spatial_resolution
    max_pixels_per_class = max_pixels_per_class or MAX_PIXELS_PER_CLASS

    train_gdf = training_gdf(known_session.id)

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

    analyzer, pixel_extract, uploaded_classes, pixel_counts = _extract(
        train_gdf, image, aoi, scale, max_pixels_per_class
    )
    sep_df = analyzer.get_separability_df(pixel_extract, method='TD')

    summary = build_summary(uploaded_classes, pixel_counts, sep_df)
    if summary is None:
        return None
    pairs = [
        {'a': str(row['Class1_Name']), 'b': str(row['Class2_Name']), 'td': float(row['TD_Distance'])}
        for _, row in sep_df.sort_values('TD_Distance').iterrows()
    ]
    return {'summary': summary, 'pixel_counts': pixel_counts, 'pairs': pairs}


def analyze_with_predictors(known_session, aoi, luma, predictor_ids, scale=None, max_pixels_per_class=None):
    """
    Separability of the training classes on the composite plus the given
    predictors, with a before/after comparison (composite only vs. composite
    plus predictors).

    Both sets are measured on the same extracted sample: Earth Engine drops a
    sample pixel when any band is masked there (radar edges, for example), so
    the 'composite' numbers here can differ a little from analyze().

    -> {'sample_quality': TD summary on the stack (same shape as analyze()),
        'comparison': separability_summary.build_comparison() plus
                      'predictors' (ids in the stack) and 'skipped'}
       or None when there is nothing to analyze.
    """
    scale = scale or luma.spatial_resolution
    max_pixels_per_class = max_pixels_per_class or MAX_PIXELS_PER_CLASS

    train_gdf = training_gdf(known_session.id)

    if train_gdf.empty or train_gdf['class_id'].nunique() < 2:
        return None

    composite, collection = build_composite(
        aoi=aoi,
        start_date=luma.start_date.strftime('%Y-%m-%d'),
        end_date=luma.end_date.strftime('%Y-%m-%d'),
        landsat_version=luma.landsat_version,
        cloud_cover=luma.cloud_cover,
        return_collection=True,
    )
    if composite is None:
        return None

    stack, selection, skipped = predictor_logic.stack_selection(luma, composite, aoi, collection, predictor_ids)

    analyzer, pixel_extract, uploaded_classes, pixel_counts = _extract(
        train_gdf, stack, aoi, scale, max_pixels_per_class
    )
    if pixel_extract.empty:
        return None

    predictor_bands = [item['band'] for item in selection]
    composite_bands = [band for band in analyzer.band_names if band not in predictor_bands]
    band_sets = {
        'composite': composite_bands,
        'with_predictors': composite_bands + predictor_bands,
    }

    td_summaries = {
        key: build_summary(
            uploaded_classes,
            pixel_counts,
            analyzer.get_separability_df(pixel_extract, method='TD', bands=bands),
        )
        for key, bands in band_sets.items()
    }
    silhouette_rows = analyzer.compare_predictor_sets(pixel_extract, band_sets).to_dict('records')

    comparison = build_comparison(band_sets, silhouette_rows, td_summaries)
    comparison['predictors'] = [item['id'] for item in selection]
    comparison['skipped'] = skipped

    return {
        'sample_quality': td_summaries['with_predictors'],
        'comparison': comparison,
    }
