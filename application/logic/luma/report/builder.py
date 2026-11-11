"""
Builds the map report for one run: Earth Engine pictures -> figures -> template
fields -> .docx.

Nothing here reads the database: `results` is the run's saved output (shape in
context.py) plus `classified_serialized`, the classified image as stored in
luma_export_job.ee_image_serialized. The caller decides where those come from.
Exercised on Sentinel-2 only so far.
"""
import ee
from shapely.geometry import shape

from application.logic.luma.composite import get_optical_collection
from luma_ge.data_acquisition import Reflectance_Data

from . import figures as fg
from .context import build_context
from .render import fill_template

TIGHT_PAD = 0.12      # frame around the area for the detail maps
WIDE_PAD = 0.9        # frame for the location map (Gambar 1)
BACKGROUND_PX = 1200


def build_figures(results):
    """Returns ({template slot: figure or None}, {earth engine render: seconds})."""
    luma, classes = results['luma'], results['classes']
    geom = shape(results['aoi']['geojson'])
    tight, wide = fg.frame_bbox(geom, TIGHT_PAD), fg.frame_bbox(geom, WIDE_PAD)

    # one composite of the run's own imagery serves every background
    collection, _meta = get_optical_collection(
        Reflectance_Data(), ee.Geometry.Rectangle(list(wide), None, False),
        luma['start_date'], luma['end_date'], luma['sensor'], luma['cloud_cover'])
    composite = collection.median()
    false_colour = composite.visualize(bands=['NIR', 'RED', 'GREEN'], min=0.02, max=0.45, gamma=1.1)
    # Landsat MSS has no blue band: fall back to false colour and skip Gambar 2b
    has_blue = 'BLUE' in composite.bandNames().getInfo()
    background = (composite.visualize(bands=['RED', 'GREEN', 'BLUE'], min=0.015, max=0.22, gamma=1.25)
                  if has_blue else false_colour)

    classified = ee.Image(ee.deserializer.decode(results['classified_serialized'])).select(0)
    class_layer = fg.classification_layer(classified, classes, ee.Geometry(results['aoi']['geojson']))

    jobs = {
        'wide': (background, wide, BACKGROUND_PX),
        'tight': (background, tight, BACKGROUND_PX),
        'classification': (class_layer, tight, fg.native_width_px(tight, luma['spatial_resolution'])),
    }
    if has_blue:
        jobs['tight_false'] = (false_colour, tight, BACKGROUND_PX)
    images, seconds = fg.fetch_all(jobs)

    thematic = results.get('thematic')
    figures = {
        'fig_aoi': fg.overview_map(images['wide'], wide, geom),
        'fig_rgb': fg.overview_map(images['tight'], tight, geom),
        'fig_fci': fg.overview_map(images['tight_false'], tight, geom) if has_blue else None,
        'fig_samples': fg.sample_map(images['tight'], tight, geom, results['training']['points'], classes),
        'fig_map': fg.class_map(images['tight'], images['classification'], tight, geom, classes),
        'fig_composition': fg.composition_chart(results['lulc_composition']),
        'fig_cm_model': fg.confusion_chart(results['model_quality']['confusion_matrix'], classes),
        'fig_cm_thematic': fg.confusion_chart(thematic['confusion_matrix'], classes) if thematic else None,
        'fig_val_points': fg.validation_map(images['tight'], tight, geom, thematic['points']) if thematic else None,
    }
    return figures, seconds


def build_docx(results, meta, template_path, out_path, figures=None):
    """Writes the filled report to out_path and returns the ids of the footnotes dropped."""
    if figures is None:
        figures, _seconds = build_figures(results)
    return fill_template(template_path, build_context(results, meta), figures, out_path)
