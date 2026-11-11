"""
Rules that turn a run's numbers into the report's words.

Two kinds live here:

  * Rules that are already fixed somewhere else -- the template's own text, or a
    threshold the app already uses. These are implemented.
  * Rules that belong to the report spec. These are NOT implemented: each one is
    marked SPEC PENDING and returns a neutral value, so the report still renders
    and the spec can be dropped in here without touching any other file.
"""
from application.logic.luma.separability_summary import GOOD_TD, WEAK_TD

# --- fixed by the template itself (Section 7: "tinggi bila OA >= 85%, sedang 70-85%, rendah di bawah 70%")
ACCURACY_HIGH = 85.0
ACCURACY_MEDIUM = 70.0
LEVEL_LABELS = {'high': 'Tinggi', 'medium': 'Sedang', 'low': 'Rendah'}


def accuracy_level(oa_pct):
    if oa_pct >= ACCURACY_HIGH:
        code = 'high'
    elif oa_pct >= ACCURACY_MEDIUM:
        code = 'medium'
    else:
        code = 'low'
    return code, LEVEL_LABELS[code]


# --- already used by the app: same thresholds and overall labels as separability_summary
TD_OVERALL_LABELS = {'good': 'Baik', 'med': 'Sedang', 'poor': 'Buruk'}


def td_label(td):
    if td >= GOOD_TD:
        return 'Baik'
    if td >= WEAK_TD:
        return 'Lemah'
    return 'Buruk'


# --- SPEC PENDING -----------------------------------------------------------------

def fitness(model_oa_pct, thematic_oa_pct):
    """
    SPEC PENDING: the map's confidence level, its list of points to watch, the
    suitability table (Tabel 10) and the recommendations (8.3).

    Until the spec arrives the level simply follows the accuracy category
    (thematic accuracy when it was tested, otherwise model accuracy), because the
    template's summary paragraph needs one of high / medium / low. The three
    lists stay empty.
    """
    code, label = accuracy_level(thematic_oa_pct if thematic_oa_pct is not None else model_oa_pct)
    return {
        'level_code': code,
        'level_label': label,
        'flags': [],            # "Hal yang perlu diperhatikan pada peta ini"
        'uses': [],             # Tabel 10: [{'use': ..., 'status': ..., 'note': ...}]
        'recommendations': [],  # 8.3 Langkah berikutnya
    }


def data_flags(low_pixel_classes):
    """
    Switches for the template's warning boxes.

    SPEC PENDING: high_cloud, few_scenes, small_val (no thresholds yet -> off).
    low_pixels is on when the app's existing check (fewer than
    separability_summary.LOW_PIXEL_COUNT valid pixels) found any class.
    """
    return {
        'high_cloud': False,
        'few_scenes': False,
        'small_val': False,
        'low_pixels': bool(low_pixel_classes),
    }


def vegetation_split(classes, composition):
    """
    SPEC PENDING: which classes count as vegetation. Returns None, which hides
    the "x% wilayah tertutup vegetasi" sentences; return
    {'veg_pct': float, 'nonveg_pct': float} to show them.
    """
    return None
