"""
The map report's figures, drawn on the server.

Earth Engine supplies the raster pictures only (a background composite and the
classification); outlines, points, legends, scale bars and both chart types are
drawn here with matplotlib, at the size they are printed. Every figure function
returns {'image': bytes, 'width_mm': printed width}: JPEG for the photo-like
maps (a tenth of the PNG size), PNG for the charts.
"""
import io
import math
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor

from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure  # plain Figure objects, no pyplot: safe when requests share a process
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from PIL import Image

from .formatting import num

PINK = '#CC4778'
INK = '#333333'
DPI = 200
MAP_WIDTH_MM = 125
MAX_MAP_HEIGHT_MM = 110   # a tall area gets a narrower map instead of most of a page
CHART_WIDTH_MM = 170      # the template's text width (A4, 2 cm margins)


# ---------------------------------------------------------------- Earth Engine side

def frame_bbox(geom, pad):
    """Bounding box of a shapely geometry, padded by a share of its size: (w, s, e, n)."""
    minx, miny, maxx, maxy = geom.bounds
    px, py = (maxx - minx) * pad, (maxy - miny) * pad
    return (minx - px, miny - py, maxx + px, maxy + py)


def native_width_px(bbox, scale_m, lo=500, hi=1400):
    """Pixels needed to show a raster of `scale_m` resolution without resampling it."""
    w, s, e, n = bbox
    lat = math.radians((s + n) / 2)
    longest_m = max((e - w) * 111320 * math.cos(lat), (n - s) * 110574)
    return int(max(lo, min(hi, round(longest_m / scale_m))))


def fetch_png(image, bbox, max_px, timeout=300):
    """One static render of an already-visualized ee.Image."""
    import ee
    import requests

    region = ee.Geometry.Rectangle(list(bbox), None, False)
    url = image.getThumbURL({'region': region, 'dimensions': int(max_px), 'format': 'png', 'crs': 'EPSG:4326'})
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return Image.open(io.BytesIO(response.content)).convert('RGBA')


def fetch_all(jobs):
    """jobs: {name: (image, bbox, max_px)} -> ({name: PIL image}, {name: seconds}), fetched in parallel."""
    def one(item):
        name, (image, bbox, max_px) = item
        started = time.time()
        return name, fetch_png(image, bbox, max_px), round(time.time() - started, 1)

    with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
        done = list(pool.map(one, jobs.items()))
    return {name: img for name, img, _ in done}, {name: secs for name, _, secs in done}


def classification_layer(classified, classes, clip_to):
    """Class ids -> 0..n-1 before colouring: a palette assumes evenly spaced values."""
    ids = [int(c['class_id']) for c in classes]
    palette = [(c['class_color'] or '#888888').lstrip('#') for c in classes]
    return (classified.remap(ids, list(range(len(ids))))
            .clip(clip_to)
            .visualize(min=0, max=max(len(ids) - 1, 1), palette=palette))


# ---------------------------------------------------------------- drawing side

def _export(fig, width_mm, photo=False):
    buf = io.BytesIO()
    if photo:
        fig.savefig(buf, format='jpg', dpi=DPI, pil_kwargs={'quality': 88})
    else:
        fig.savefig(buf, format='png', dpi=DPI)
    return {'image': buf.getvalue(), 'width_mm': width_mm}


def _wrap(text, width):
    return '\n'.join(textwrap.wrap(text, width)) or text


def map_width_mm(bbox):
    """Printed width of a map frame: the standard width, narrowed when the frame is tall."""
    w, s, e, n = bbox
    ratio = (n - s) / math.cos(math.radians((s + n) / 2)) / (e - w)
    return min(MAP_WIDTH_MM, MAX_MAP_HEIGHT_MM / ratio)


class MapFigure:
    """A background picture in geographic coordinates with vector overlays on top."""

    def __init__(self, background, bbox, legend_lines=0):
        self.bbox = bbox
        self.width_mm = map_width_mm(bbox)
        w, s, e, n = bbox
        self.lat = (s + n) / 2
        self.aspect = 1 / math.cos(math.radians(self.lat))
        width_in = self.width_mm / 25.4
        map_h = width_in * (n - s) * self.aspect / (e - w)
        legend_h = 0.135 * legend_lines + 0.1 if legend_lines else 0
        total = map_h + legend_h
        self.fig = Figure(figsize=(width_in, total))
        self.ax = self.fig.add_axes([0, legend_h / total, 1, map_h / total])
        self.ax.imshow(background, extent=[w, e, s, n], interpolation='lanczos')
        self.ax.set_aspect(self.aspect)
        self.ax.set_xlim(w, e)
        self.ax.set_ylim(s, n)
        self.ax.axis('off')

    def overlay(self, image):
        w, s, e, n = self.bbox
        self.ax.imshow(image, extent=[w, e, s, n], interpolation='nearest')
        return self

    def outline(self, geom):
        for part in (geom.geoms if geom.geom_type == 'MultiPolygon' else [geom]):
            xs, ys = part.exterior.xy
            self.ax.plot(xs, ys, color='white', linewidth=2.4, solid_joinstyle='round')
            self.ax.plot(xs, ys, color=PINK, linewidth=1.3, solid_joinstyle='round')
        return self

    def points(self, lons, lats, colors, size=26):
        self.ax.scatter(lons, lats, s=size, c=colors, edgecolors='white', linewidths=0.8, zorder=5)
        return self

    def scale_bar(self):
        w, s, e, n = self.bbox
        km_per_deg = 111.32 * math.cos(math.radians(self.lat))
        width_km = (e - w) * km_per_deg
        nice = max(k for k in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200) if k <= max(width_km / 4, 0.1))
        x0, y0 = w + 0.04 * (e - w), s + 0.045 * (n - s)
        x1 = x0 + nice / km_per_deg
        self.ax.plot([x0, x1], [y0, y0], color='black', linewidth=4.0, solid_capstyle='butt')
        self.ax.plot([x0, x1], [y0, y0], color='white', linewidth=2.2, solid_capstyle='butt')
        label = '{:g} km'.format(nice) if nice >= 1 else '{:g} m'.format(nice * 1000)
        self.ax.text(x1 + 0.012 * (e - w), y0, label, color='white', fontsize=6.5, va='center',
                     bbox=dict(facecolor='black', alpha=0.45, edgecolor='none', pad=1.2))
        return self

    def legend(self, handles, ncol=2):
        self.fig.legend(handles=handles, loc='lower center', bbox_to_anchor=(0.5, 0.0), ncol=ncol,
                        fontsize=6.5, frameon=False, handlelength=1.3, handleheight=0.9,
                        columnspacing=1.6, labelspacing=0.45, borderaxespad=0.15)
        return self

    def export(self):
        return _export(self.fig, self.width_mm, photo=True)


def class_legend(classes, width_mm):
    """Legend handles for the class scheme, and how many text lines a two-column legend needs."""
    wrap = max(18, int((width_mm / 25.4 / 2 - 0.4) / 0.05))
    handles, lines = [], []
    for c in classes:
        label = _wrap(c['class_name'], wrap)
        lines.append(label.count('\n') + 1)
        handles.append(Patch(facecolor=c['class_color'], edgecolor='#9a9a9a', linewidth=0.4, label=label))
    half = math.ceil(len(lines) / 2)
    return handles, max(sum(lines[:half]), sum(lines[half:]))


def overview_map(background, bbox, geom):
    return MapFigure(background, bbox).outline(geom).scale_bar().export()


def class_map(background, classification, bbox, geom, classes):
    handles, lines = class_legend(classes, map_width_mm(bbox))
    return (MapFigure(background, bbox, legend_lines=lines)
            .overlay(classification).outline(geom).scale_bar().legend(handles).export())


def sample_map(background, bbox, geom, points, classes):
    handles, lines = class_legend(classes, map_width_mm(bbox))
    color = {c['class_id']: c['class_color'] for c in classes}
    return (MapFigure(background, bbox, legend_lines=lines).outline(geom)
            .points([p['lon'] for p in points], [p['lat'] for p in points],
                    [color.get(p['class_id'], '#888888') for p in points])
            .scale_bar().legend(handles).export())


def validation_map(background, bbox, geom, points):
    ok, bad = '#1FA971', '#E5484D'
    handles = [Line2D([], [], marker='o', linestyle='', markersize=5, markerfacecolor=ok,
                      markeredgecolor='white', label='Sesuai'),
               Line2D([], [], marker='o', linestyle='', markersize=5, markerfacecolor=bad,
                      markeredgecolor='white', label='Tidak sesuai')]
    return (MapFigure(background, bbox, legend_lines=1).outline(geom)
            .points([p['lon'] for p in points], [p['lat'] for p in points],
                    [ok if p['is_correct'] else bad for p in points])
            .scale_bar().legend(handles).export())


def composition_chart(composition, width_mm=CHART_WIDTH_MM):
    """composition: the saved lulc_composition list (largest first)."""
    areas = [c['area_m2'] / 10000.0 for c in composition]
    fig = Figure(figsize=(width_mm / 25.4, 0.36 * len(composition) + 0.75))
    ax = fig.subplots()
    ys = range(len(composition))
    ax.barh(ys, areas, color=[c['class_color'] for c in composition], edgecolor='#00000022', linewidth=0.5)
    ax.set_yticks(list(ys))
    ax.set_yticklabels([_wrap(c['class_name'], 30) for c in composition], fontsize=7, color=INK)
    ax.invert_yaxis()
    top = max(areas) if areas else 1
    for y, area, c in zip(ys, areas, composition):
        ax.text(area + top * 0.012, y, '{} ha · {}%'.format(num(area), num(c['proportion'], 1)),
                va='center', fontsize=7, color=INK)
    ax.set_xlim(0, top * 1.24)
    ax.set_xlabel('Luas (ha)', fontsize=7.5, color=INK)
    ax.tick_params(axis='x', labelsize=7, colors=INK)
    ax.tick_params(axis='y', length=0)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    for side in ('left', 'bottom'):
        ax.spines[side].set_color('#BBBBBB')
    fig.tight_layout()
    return _export(fig, width_mm)


def confusion_chart(matrix, classes, width_mm=150):
    """matrix is indexed by class id (rows actual, columns predicted); only the scheme's classes are shown."""
    ids = [int(c['class_id']) for c in classes]

    def cell(i, j):
        return int(matrix[i][j]) if i < len(matrix) and j < len(matrix[i]) else 0

    grid = [[cell(i, j) for j in ids] for i in ids]
    peak = max(1, max(max(row) for row in grid))
    # names on the rows, ids on the columns: long names cannot collide under the grid
    row_labels = ['{} · {}'.format(c['class_id'], _wrap(c['class_name'], 24)) for c in classes]
    width_in = width_mm / 25.4
    fig = Figure(figsize=(width_in, width_in * 0.7))
    ax = fig.subplots()
    cmap = LinearSegmentedColormap.from_list('luma', ['#FFFFFF', '#F6CBDA', PINK])
    ax.imshow(grid, cmap=cmap, vmin=0, vmax=peak)
    ax.set_xticks(range(len(ids)))
    ax.set_yticks(range(len(ids)))
    ax.set_xticklabels([str(i) for i in ids], fontsize=7, color=INK)
    ax.set_yticklabels(row_labels, fontsize=6.5, color=INK)
    ax.set_xlabel('Kelas prediksi (ID kelas)', fontsize=7.5, color=INK)
    ax.set_ylabel('Kelas sebenarnya', fontsize=7.5, color=INK)
    for i, row in enumerate(grid):
        for j, value in enumerate(row):
            ax.text(j, i, str(value), ha='center', va='center', fontsize=7,
                    fontweight='bold' if i == j and value else 'normal',
                    color='white' if value > 0.6 * peak else (INK if value else '#B8B8B8'))
    ax.set_xticks([x - 0.5 for x in range(1, len(ids))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(ids))], minor=True)
    ax.grid(which='minor', color='#E3E3E3', linewidth=0.6)
    ax.tick_params(which='both', length=0)
    for spine in ax.spines.values():
        spine.set_color('#BBBBBB')
    fig.tight_layout()
    return _export(fig, width_mm)
