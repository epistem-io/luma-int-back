# Pure summary builder for separability analysis. Kept free of application/EE
# imports so it can be unit-tested without initializing Earth Engine.

GOOD_TD = 1.8
WEAK_TD = 1.0
LOW_PIXEL_COUNT = 5


def _overall_label(mean_td):
    if mean_td >= GOOD_TD:
        return 'good'
    if mean_td >= WEAK_TD:
        return 'med'
    return 'poor'


def build_summary(uploaded_classes, pixel_counts, sep_df):
    """
    uploaded_classes: [{'class_id': int, 'class_name': str}] from the session's
        training data (every class the user provided)
    pixel_counts: {class_id(int): extracted pixel count} after sampleRegions
    sep_df: DataFrame from luma_ge get_separability_df (Class*_ID are strings)
    """
    if sep_df.empty:
        return None

    mean_td = float(sep_df['TD_Distance'].mean())

    good_pairs = int((sep_df['TD_Distance'] >= GOOD_TD).sum())
    weak_pairs = int(((sep_df['TD_Distance'] >= WEAK_TD) & (sep_df['TD_Distance'] < GOOD_TD)).sum())
    poor_pairs = int((sep_df['TD_Distance'] < WEAK_TD).sum())

    problem_df = sep_df[sep_df['TD_Distance'] < GOOD_TD]

    analyzed_class_ids = {int(c) for c in set(sep_df['Class1_ID']).union(sep_df['Class2_ID'])}
    problem_class_ids = {int(c) for c in set(problem_df['Class1_ID']).union(problem_df['Class2_ID'])}

    classes_dropped = [
        {
            'class_id': c['class_id'],
            'class_name': c['class_name'],
            'reason': 'no valid pixels (masked/cloud-covered imagery at sample locations)',
        }
        for c in uploaded_classes if c['class_id'] not in analyzed_class_ids
    ]

    low_sample_classes = [
        {
            'class_id': c['class_id'],
            'class_name': c['class_name'],
            'pixels': int(pixel_counts.get(c['class_id'], 0)),
        }
        for c in uploaded_classes
        if c['class_id'] in analyzed_class_ids
        and pixel_counts.get(c['class_id'], 0) < LOW_PIXEL_COUNT
    ]

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
        'classes_good': len(analyzed_class_ids) - len(problem_class_ids),
        'classes_total': len(uploaded_classes),
        'classes_analyzed': len(analyzed_class_ids),
        'classes_dropped': classes_dropped,
        'low_sample_classes': low_sample_classes,
        'problem_pairs': problem_pairs
    }
