import geopandas as gpd

from application import db
from application.logic.geos.aoi import converter
from application.logic.luma.composite import build_composite

from luma_ge.sample_data_quality import sample_quality

MAX_PIXELS_PER_CLASS = 5000

GOOD_TD = 1.8
WEAK_TD = 1.0

def _overall_label(mean_td):
    if mean_td >= GOOD_TD:
        return 'good'
    if mean_td >= WEAK_TD:
        return 'med'
    return 'poor'

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
    sep_df =analyzer.get_separability_df(pixel_extract, method='TD')
    if sep_df.empty:
        return None
    
    mean_td = float(sep_df['TD_Distance'].mean())
    
    good_pairs = int((sep_df['TD_Distance'] >= GOOD_TD).sum())
    weak_pairs = int(((sep_df['TD_Distance'] >= WEAK_TD) & (sep_df['TD_Distance'] < GOOD_TD)).sum())
    poor_pairs = int((sep_df['TD_Distance'] < WEAK_TD).sum())
    
    problem_df = sep_df[sep_df['TD_Distance'] < GOOD_TD]
    
    all_class_ids = set(sep_df['Class1_ID']).union(sep_df['Class2_ID'])
    problem_class_ids = set(problem_df['Class1_ID']).union(problem_df['Class2_ID'])
    
    problem_pairs = []
    for _, row in problem_df.iterrows():
        problem_pairs.append({
            'Class1_ID': str(row['Class1_ID']),
            'Class1_Name': str(row['Class1_Name']),
            'Class2_ID': str(row['Class2_ID']),
            'Class2_Name': str(row['Class2_Name']),
            'TD_Distance': float(row['TD_Distance']),
            'Separability_Level': str(row['Separability_Level'])
        })
        
    return {
        'mean_td': round(mean_td, 2),
        'overall': _overall_label(mean_td),
        'pair_counts': {
            'good': good_pairs,
            'weak': weak_pairs,
            'poor': poor_pairs,
            'total': int(len(sep_df))
        },
        'classes_good': len(all_class_ids) - len(problem_class_ids),
        'classes_total': len(all_class_ids),
        'problem_pairs': problem_pairs
    }