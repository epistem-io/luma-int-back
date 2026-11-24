"""
The map report, drawn straight to PDF with ReportLab.

Takes the fields from context.build_context and the figures from
builder.build_figures and returns the PDF as bytes. This file is the report's
template: its wording and layout live here (they were ported from the original
Word template, Luma_Report_Template.docx).

Things that differ from that Word template, on purpose:
  * footnotes are numbered notes at the end of their section (ReportLab has no
    page-bottom footnotes);
  * the scene table's "Path/Row" heading and the imagery source note follow the
    sensor, so a Sentinel-2 report does not cite Landsat;
  * the contents table's entries are links, and the PDF carries bookmarks.
"""
import io
import os
import re
from xml.sax.saxutils import escape as E

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, HRFlowable, Image, KeepTogether,
                                NextPageTemplate, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.platypus.doctemplate import IndexingFlowable
from reportlab.platypus.tableofcontents import TableOfContents

MARGIN = 20 * mm
WIDTH = A4[0] - 2 * MARGIN  # 170 mm of text

PINK = colors.HexColor('#CC4778')
PINK_DARK = colors.HexColor('#B0305F')
PINK_HEAD = colors.HexColor('#FBE3EC')
PINK_PALE = colors.HexColor('#FDF0F4')
PINK_RULE = colors.HexColor('#F0B8CC')
INK = colors.HexColor('#222222')
GREY = colors.HexColor('#6B6B6B')
RULE = colors.HexColor('#DDDDDD')
GREY_BOX = colors.HexColor('#F3F3F3')
ORANGE = colors.HexColor('#F0A030')
ORANGE_PALE = colors.HexColor('#FFF3E0')
ORANGE_TEXT = colors.HexColor('#A65E00')
BOXES = {  # kind -> (background, left bar, title colour)
    'grey': (GREY_BOX, colors.HexColor('#C8C8C8'), PINK_DARK),
    'pink': (PINK_PALE, PINK, PINK_DARK),
    'orange': (ORANGE_PALE, ORANGE, ORANGE_TEXT),
}

COVER_BANNER = os.path.join(os.path.dirname(__file__), 'assets', 'cover_banner.png')

# A font with the report's characters (≥, →, –, ·). Arial where Windows has it,
# Liberation Sans on the server (same letter widths as Arial, so the pages break
# the same way), otherwise the DejaVu Sans that ships with matplotlib.
_FONT_SETS = (
    [r'C:\Windows\Fonts\arial.ttf', r'C:\Windows\Fonts\arialbd.ttf',
     r'C:\Windows\Fonts\ariali.ttf', r'C:\Windows\Fonts\arialbi.ttf'],
    ['/usr/share/fonts/truetype/liberation/LiberationSans-{}.ttf'.format(v)
     for v in ('Regular', 'Bold', 'Italic', 'BoldItalic')],
    ['/usr/share/fonts/truetype/liberation2/LiberationSans-{}.ttf'.format(v)
     for v in ('Regular', 'Bold', 'Italic', 'BoldItalic')],
)


def _font_files():
    for files in _FONT_SETS:
        if all(os.path.isfile(f) for f in files):
            return files
    import matplotlib
    base = os.path.join(matplotlib.get_data_path(), 'fonts', 'ttf')
    return [os.path.join(base, n) for n in
            ('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf', 'DejaVuSans-Oblique.ttf', 'DejaVuSans-BoldOblique.ttf')]


def _register_fonts():
    if 'Luma' in pdfmetrics.getRegisteredFontNames():
        return
    for name, path in zip(('Luma', 'Luma-Bold', 'Luma-Italic', 'Luma-BoldItalic'), _font_files()):
        pdfmetrics.registerFont(TTFont(name, path))
    pdfmetrics.registerFontFamily('Luma', normal='Luma', bold='Luma-Bold',
                                  italic='Luma-Italic', boldItalic='Luma-BoldItalic')


def _styles():
    def st(name, **kw):
        base = dict(fontName='Luma', fontSize=9.5, leading=13.5, textColor=INK)
        base.update(kw)
        return ParagraphStyle(name, **base)

    return {
        'body': st('body', spaceAfter=6),
        'small': st('small', fontSize=7.5, leading=10, textColor=GREY, spaceAfter=1.5),
        'note': st('note', fontName='Luma-Italic', fontSize=8, leading=10.5, textColor=GREY, spaceBefore=3, spaceAfter=6),
        'caption': st('caption', fontName='Luma-Italic', fontSize=8, leading=10.5, textColor=GREY,
                      alignment=TA_CENTER, spaceBefore=3, spaceAfter=8),
        'h1': st('h1', fontName='Luma-Bold', fontSize=16, leading=20, textColor=PINK, spaceBefore=10, keepWithNext=1),
        'h2': st('h2', fontName='Luma-Bold', fontSize=11.5, leading=15, textColor=PINK_DARK,
                 spaceBefore=8, spaceAfter=3, keepWithNext=1),
        'toc_title': st('toc_title', fontName='Luma-Bold', fontSize=16, leading=20, textColor=PINK),
        'table_title': st('table_title', fontName='Luma-Bold', fontSize=8.5, leading=11, textColor=PINK_DARK,
                          spaceBefore=6, spaceAfter=3),
        'th': st('th', fontName='Luma-Bold', fontSize=8.5, leading=11, textColor=PINK_DARK),
        'th_r': st('th_r', fontName='Luma-Bold', fontSize=8.5, leading=11, textColor=PINK_DARK, alignment=TA_RIGHT),
        'td': st('td', fontSize=8.5, leading=11),
        'td_r': st('td_r', fontSize=8.5, leading=11, alignment=TA_RIGHT),
        'kv': st('kv', fontName='Luma-Bold', fontSize=8.5, leading=11, textColor=GREY),
        'card_label': st('card_label', fontSize=7.5, leading=10, textColor=GREY),
        'card_value': st('card_value', fontName='Luma-Bold', fontSize=14, leading=17, textColor=PINK),
        'box_title': st('box_title', fontName='Luma-Bold', fontSize=9, leading=12),
        'box_text': st('box_text', fontSize=8.5, leading=11.5),
        'bullet': st('bullet', leftIndent=16, bulletIndent=5, spaceAfter=3),
        'ref': st('ref', fontSize=8, leading=10.5, leftIndent=14, firstLineIndent=-14, spaceAfter=3),
        'cover_kicker': st('cover_kicker', fontSize=9.5, textColor=PINK),
        'cover_title': st('cover_title', fontName='Luma-Bold', fontSize=25, leading=31, textColor=PINK),
        'cover_name': st('cover_name', fontSize=15, leading=19),
        'cover_sub': st('cover_sub', fontSize=11, leading=14, textColor=GREY, spaceAfter=10),
        'cover_block_title': st('cover_block_title', fontName='Luma-Bold', fontSize=14, leading=18, textColor=colors.white),
        'cover_block_text': st('cover_block_text', fontSize=8.5, leading=11.5, textColor=colors.white),
        'toc1': st('toc1', fontName='Luma-Bold', fontSize=10, leading=16),
        'toc2': st('toc2', fontSize=8.5, leading=12, leftIndent=14, textColor=GREY),
    }


GLOSSARY = (
    ('Citra komposit', 'Gabungan beberapa citra satelit dalam satu periode yang piksel berawannya dibuang.'),
    ('Data sampel / validasi', 'Lokasi berkelas lahan diketahui; sampel untuk melatih model, validasi (terpisah) untuk menguji peta.'),
    ('LULC', 'Land Use and Land Cover: penggunaan lahan (fungsi bagi manusia) dan tutupan lahan (yang menutupi permukaan).'),
    ('Matriks kesalahan', 'Tabel yang membandingkan kelas sebenarnya dengan kelas hasil peta pada lokasi uji.'),
    ('Piksel / resolusi spasial', 'Kotak terkecil penyusun peta; resolusi adalah panjang sisinya di lapangan (mis. 30 m).'),
    ('Prediktor / indeks spektral', 'Data masukan model; indeks spektral adalah rumus kanal citra untuk menonjolkan objek, mis. NDVI untuk vegetasi.'),
    ('Random Forest', 'Metode pembelajaran mesin yang menggabungkan banyak pohon keputusan dengan suara terbanyak.'),
    ('Selang kepercayaan', 'Rentang nilai yang kemungkinan besar memuat akurasi sebenarnya.'),
    ('Transformed Divergence', 'Ukuran keterpisahan spektral dua kelas, bernilai 0–2.'),
)
REFERENCES = (
    'Anderson, J. R., Hardy, E. E., Roach, J. T., &amp; Witmer, R. E. (1976). A Land Use and Land Cover Classification System for Use with Remote Sensor Data. USGS Professional Paper 964.',
    'Badan Informasi Geospasial. Batas wilayah administrasi Indonesia. Diakses melalui Google Earth Engine.',
    'Breiman, L. (2001). Random forests. Machine Learning, 45(1), 5–32.',
    'Cohen, J. (1960). A coefficient of agreement for nominal scales. Educational and Psychological Measurement, 20(1), 37–46.',
    'Congalton, R. G. (1991). A review of assessing the accuracy of classifications of remotely sensed data. Remote Sensing of Environment, 37(1), 35–46.',
    'Epistem. Luma Development Reference. https://epistem-io.github.io/luma-dr/',
    'Gorelick, N., Hancher, M., Dixon, M., Ilyushchenko, S., Thau, D., &amp; Moore, R. (2017). Google Earth Engine: Planetary-scale geospatial analysis for everyone. Remote Sensing of Environment, 202, 18–27.',
    'Landis, J. R., &amp; Koch, G. G. (1977). The measurement of observer agreement for categorical data. Biometrics, 33(1), 159–174.',
    'Montero, D., et al. (2023). A standardized catalogue of spectral indices to advance the use of remote sensing in Earth system research. Scientific Data, 10, 197.',
    'Olofsson, P., Foody, G. M., Herold, M., Stehman, S. V., Woodcock, C. E., &amp; Wulder, M. A. (2014). Good practices for estimating area and assessing accuracy of land change. Remote Sensing of Environment, 148, 42–57.',
    'Swain, P. H., &amp; Davis, S. M. (Eds.). (1978). Remote Sensing: The Quantitative Approach. McGraw-Hill.',
    'U.S. Geological Survey. Landsat Collection 2 Level-2 Surface Reflectance. Diakses melalui Google Earth Engine.',
)


class _Doc(BaseDocTemplate):
    """Cover page without header or footer, then body pages; headings feed the table of contents."""

    def __init__(self, target, header, footer, draw_cover_block):
        super().__init__(target, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                         topMargin=MARGIN, bottomMargin=MARGIN, title=header)
        self._header = header
        self._footer = footer
        self._heading_no = 0
        self.total_pages = 0      # page count of the previous build pass, printed in the footer
        self.pages_this_pass = 0
        frame = Frame(MARGIN, MARGIN, WIDTH, A4[1] - 2 * MARGIN, leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0, id='body')
        self.addPageTemplates([
            PageTemplate(id='cover', frames=[frame], onPage=draw_cover_block),
            PageTemplate(id='body', frames=[frame], onPage=self._draw_header_footer),
        ])

    def _draw_header_footer(self, canv, doc):
        canv.saveState()
        canv.setFont('Luma', 7)
        canv.setFillColor(GREY)
        canv.drawRightString(A4[0] - MARGIN, A4[1] - 12 * mm, self._header)
        canv.setStrokeColor(PINK_RULE)
        canv.setLineWidth(0.5)
        canv.line(MARGIN, 14 * mm, A4[0] - MARGIN, 14 * mm)
        canv.drawString(MARGIN, 10 * mm, '{}  |  Hal. {} dari {}'.format(self._footer, doc.page, self.total_pages or doc.page))
        canv.restoreState()

    def afterPage(self):
        self.pages_this_pass = self.page

    def afterFlowable(self, flowable):
        level = getattr(flowable, '_toc_level', None)
        if level is None:
            return
        self._heading_no += 1
        key = 'heading-{}'.format(self._heading_no)
        text = flowable.getPlainText()
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text, key, level, 0)
        self.notify('TOCEntry', (level, text, self.page, key))

    def beforeDocument(self):
        self._heading_no = 0  # the build runs more than once to settle the page numbers


class _PageCount(IndexingFlowable):
    """
    Invisible marker at the end of the story. ReportLab already builds the
    document more than once to settle the table of contents; this makes it keep
    going until the page total printed in the footer ("Hal. X dari N") is the
    real one.
    """

    def __init__(self, doc):
        super().__init__()
        self.doc = doc

    def beforeBuild(self):
        self.doc.total_pages = self.doc.pages_this_pass

    def isSatisfied(self):
        return self.doc.total_pages == self.doc.pages_this_pass

    def wrap(self, avail_width, avail_height):
        return 0, 0

    def draw(self):
        pass


class _Report:
    def __init__(self, ctx, figures):
        self.c = ctx
        self.figs = figures
        self.banner = COVER_BANNER
        self.S = _styles()
        self.story = []
        self.notes = []
        self.note_no = 0

    # ------------------------------------------------------------ building blocks

    def add(self, *flowables):
        self.story.extend(flowables)

    def p(self, text, style='body'):
        self.add(Paragraph(text, self.S[style]))

    def h1(self, text):
        self.flush_notes()
        heading = Paragraph(E(text), self.S['h1'])
        heading._toc_level = 0
        rule = HRFlowable(width='100%', thickness=0.7, color=PINK_RULE, spaceBefore=1, spaceAfter=7)
        rule.keepWithNext = 1
        self.add(heading, rule)

    def h2(self, text):
        heading = Paragraph(E(text), self.S['h2'])
        heading._toc_level = 1
        self.add(heading)

    def fn(self, text):
        """Registers a source note and returns its superscript mark."""
        self.note_no += 1
        self.notes.append((self.note_no, text))
        return '<super>{}</super>'.format(self.note_no)

    def flush_notes(self):
        if not self.notes:
            return
        block = [Spacer(1, 5), HRFlowable(width='28%', thickness=0.5, color=GREY, hAlign='LEFT', spaceAfter=3)]
        block += [Paragraph('<super>{}</super> {}'.format(number, text), self.S['small']) for number, text in self.notes]
        self.add(KeepTogether(block))
        self.notes = []

    def bullets(self, items, numbered=False):
        for i, text in enumerate(items, start=1):
            self.add(Paragraph(text, self.S['bullet'], bulletText='{}.'.format(i) if numbered else '•'))

    def box(self, title, text, kind):
        background, bar, title_colour = BOXES[kind]
        title_style = ParagraphStyle('bt', parent=self.S['box_title'], textColor=title_colour)
        cell = ([Paragraph(title, title_style)] if title else []) + [Paragraph(text, self.S['box_text'])]
        t = Table([[cell]], colWidths=[WIDTH])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), background),
            ('LINEBEFORE', (0, 0), (0, -1), 3, bar),
            ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ]))
        self.add(Spacer(1, 3), t, Spacer(1, 8))

    def cards(self, items):
        """items: [(label, value, sub)] -> one row of stat cards."""
        row = [[Paragraph(E(label), self.S['card_label']), Paragraph(E(value), self.S['card_value'])]
               + ([Paragraph(E(sub), self.S['card_label'])] if sub else []) for label, value, sub in items]
        t = Table([row], colWidths=[WIDTH / len(items)] * len(items))
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), PINK_PALE),
            ('INNERGRID', (0, 0), (-1, -1), 4, colors.white),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8), ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ]))
        self.add(t, Spacer(1, 10))

    def kv_table(self, rows, title=None, label_mm=58):
        if title:
            self.add(CondPageBreak((8 * len(rows) + 12) * mm))  # short table: keep it whole with its title
            self.p(title, 'table_title')
        data = [[Paragraph(label, self.S['kv']), Paragraph(value, self.S['td'])] for label, value in rows]
        t = Table(data, colWidths=[label_mm * mm, WIDTH - label_mm * mm])
        t.setStyle(TableStyle([
            ('LINEABOVE', (0, 0), (-1, 0), 0.5, RULE), ('LINEBELOW', (0, 0), (-1, -1), 0.5, RULE),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 5), ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        self.add(t, Spacer(1, 6))

    def table(self, title, header, rows, widths_mm, right=(), swatch=None):
        """rows: lists of already-escaped strings. right: right-aligned columns. swatch: (column, [hex per row])."""
        data = [[Paragraph(h, self.S['th_r' if i in right else 'th']) for i, h in enumerate(header)]]
        for row in rows:
            data.append([Paragraph(str(v), self.S['td_r' if i in right else 'td']) for i, v in enumerate(row)])
        t = Table(data, colWidths=[w * mm for w in widths_mm], repeatRows=1)
        commands = [
            ('BACKGROUND', (0, 0), (-1, 0), PINK_HEAD),
            ('GRID', (0, 0), (-1, -1), 0.5, RULE),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]
        if swatch:
            column, hexes = swatch
            for r, code in enumerate(hexes, start=1):
                if code and re.fullmatch(r'[0-9A-Fa-f]{6}', code):  # a malformed colour just leaves the cell blank
                    commands.append(('BACKGROUND', (column, r), (column, r), colors.HexColor('#' + code)))
        t.setStyle(TableStyle(commands))
        # A table that fits in under half a page stays whole; a longer one (the scene
        # list can be long) may run on to the next page, but never starts with
        # fewer than a few rows under its title.
        _w, height = t.wrap(WIDTH, 10000)
        self.add(CondPageBreak(height + 9 * mm if height <= 115 * mm else 34 * mm))
        if title:
            self.p(title, 'table_title')
        self.add(t, Spacer(1, 8))

    def figure(self, name, caption):
        fig = self.figs.get(name)
        if not fig:
            return
        w, h = PILImage.open(io.BytesIO(fig['image'])).size
        width = fig['width_mm'] * mm
        picture = Image(io.BytesIO(fig['image']), width=width, height=width * h / w)
        picture.hAlign = 'CENTER'
        picture.keepWithNext = 1  # stays with its caption, and lets a heading above stay with both
        self.add(picture, Paragraph(caption, self.S['caption']))

    # ------------------------------------------------------------ pages

    def draw_cover_block(self, canv, doc):
        """The pink "about Luma" block at the foot of the cover page."""
        block_h, banner_h = 88 * mm, WIDTH * 264 / 1152
        x, y = MARGIN, MARGIN
        canv.saveState()
        canv.setFillColor(PINK)
        canv.rect(x, y, WIDTH, block_h, stroke=0, fill=1)
        if self.banner and os.path.isfile(self.banner):
            canv.drawImage(self.banner, x, y + block_h - banner_h, width=WIDTH, height=banner_h)
        inner, cursor = WIDTH - 16 * mm, y + block_h - banner_h - 6 * mm
        for text, style in (
            ('Peta tutupan lahan, untuk semua.', 'cover_block_title'),
            ('Luma (Land Use Mapping for All) adalah aplikasi berbasis cloud tanpa koding untuk membuat peta '
             'penggunaan dan tutupan lahan dari citra satelit publik. Pengguna memilih wilayah dan periode, '
             'menentukan kelas lahan, dan memberi contoh lokasi; Luma lalu melatih model, menghasilkan peta, '
             'dan mengukur akurasinya.', 'cover_block_text'),
            ('Bagian dari <b>Epistem</b>   ·   luma.epistem.io', 'cover_block_text'),
        ):
            para = Paragraph(text, self.S[style])
            _w, h = para.wrap(inner, block_h)
            cursor -= h
            para.drawOn(canv, x + 8 * mm, cursor)
            cursor -= 3 * mm
        canv.restoreState()

    def cover(self):
        c = self.c
        r, a, pe, im = c['report'], c['aoi'], c['period'], c['imagery']
        self.add(Spacer(1, 4 * mm))
        self.p('Laporan Peta  ·  Luma Powered by Epistem', 'cover_kicker')
        self.add(Spacer(1, 5 * mm))
        self.p('Laporan Peta Penggunaan<br/>dan Tutupan Lahan', 'cover_title')
        self.add(Spacer(1, 22 * mm))
        self.p(E(r['map_name']), 'cover_name')
        self.p('{}  ·  Periode {}'.format(E(a['display_name']), E(pe['period_label'])), 'cover_sub')
        prepared = E(r['prepared_by']) + (' — ' + E(r['organization']) if r['organization'] else '')
        self.kv_table([
            ('Disiapkan oleh', prepared),
            ('Wilayah pemetaan', '{} ({} ha)'.format(E(a['display_name']), a['area_ha'])),
            ('Periode &amp; citra', '{} · {} · {}'.format(pe['date_range'], E(im['sensor']), a['resolution_label'])),
            ('ID Proyek / ID Sesi', '{} / {}'.format(E(r['project_id']), E(r['session_id']))),
            ('Tanggal terbit', '{} · Laporan v{} · Luma {}'.format(r['issued_date'], E(r['report_version']), E(r['luma_version']))),
            ('Kontak', E(r['contact'])),
        ])
        self.add(NextPageTemplate('body'), PageBreak())

    def contents(self):
        toc = TableOfContents()
        toc.levelStyles = [self.S['toc1'], self.S['toc2']]
        toc.dotsMinLevel = 0
        self.add(Paragraph('Daftar Isi', self.S['toc_title']),
                 HRFlowable(width='100%', thickness=1, color=PINK, spaceBefore=1, spaceAfter=6), toc, Spacer(1, 10))
        self.box('Penting dibaca sebelum menggunakan laporan ini',
                 'Laporan ini dibuat otomatis oleh Luma dari wilayah, periode, data sampel, dan pengaturan yang '
                 'dimasukkan pengguna. Peta dan angka di dalamnya adalah hasil pemodelan citra satelit, sehingga '
                 'mengandung ketidakpastian dan kesalahan klasifikasi. Laporan ini bukan peta resmi dan tidak boleh '
                 'menjadi satu-satunya dasar keputusan hukum, perizinan, keuangan, atau klaim karbon. Padukan dengan '
                 'data lapangan dan penilaian ahli. Penafian lengkap ada di Bagian 9.', 'grey')
        self.add(PageBreak())

    def summary(self):
        c = self.c
        a, pe, im, cl, res, ma, th, fit = (c['aoi'], c['period'], c['imagery'], c['classif'], c['result'],
                                           c['model_acc'], c['thematic'], c['fitness'])
        top = res['top']
        self.h1('Ringkasan')
        self.cards([
            ('Luas wilayah', '{} ha'.format(a['area_ha']), '{} kelas dipetakan'.format(cl['n_classes'])),
            ('Tutupan terluas', '{}%'.format(top[0]['pct']), top[0]['name']),
            ('Akurasi model', '{}%'.format(ma['oa']), 'Kategori {}'.format(ma['level_label'])),
            ('Tingkat keyakinan peta', fit['level_label'], 'Sudah uji tematik' if th['done'] else 'Belum uji tematik'),
        ])
        self.p('Peta ini menggambarkan penggunaan dan tutupan lahan di {} seluas sekitar {} hektare untuk periode {}. '
               'Peta disusun dengan Luma dari gabungan {} citra satelit {} pada resolusi {}, dan membagi lahan ke '
               'dalam {} kelas menurut {}.'.format(E(a['display_name']), a['area_ha'], E(pe['period_label']),
                                                   im['scene_count'], E(im['sensor']), a['resolution_label'],
                                                   cl['n_classes'], cl['scheme_label']))
        text = 'Tutupan lahan yang paling luas adalah {}, sekitar {} ha atau {}% wilayah, disusul {} ({}%)'.format(
            E(top[0]['name']), top[0]['area_ha'], top[0]['pct'], E(top[1]['name']), top[1]['pct'])
        if len(top) > 2:
            text += ' dan {} ({}%)'.format(E(top[2]['name']), top[2]['pct'])
        text += '.'
        if res['has_veg_split']:
            text += ' Secara keseluruhan, {}% wilayah tertutup vegetasi dan {}% berupa tutupan non-vegetasi.'.format(
                res['veg_pct'], res['nonveg_pct'])
        self.p(text)
        text = 'Dalam pengujian internal, model mengenali kelas dengan benar pada {}% sampel uji (kategori {}).'.format(
            ma['oa'], ma['level_label'])
        if th['done']:
            text += (' Pengujian terhadap {} titik validasi independen menghasilkan akurasi tematik {}%, dengan selang '
                     'kepercayaan 95% antara {}.'.format(th['n_points'], th['oa'], th['ci']))
        else:
            text += (' Akurasi tematik belum diuji karena belum ada data validasi independen, sehingga tingkat '
                     'keyakinan peta belum dapat dipastikan.')
        self.p(text)
        self.p({
            'high': 'Dengan tingkat akurasi ini, peta dapat menjadi acuan awal untuk perencanaan tingkat lanskap. '
                    'Untuk keputusan di tingkat tapak, hasilnya tetap perlu diperiksa di lapangan.',
            'medium': 'Dengan tingkat akurasi ini, peta cocok untuk melihat gambaran umum dan menandai area yang perlu '
                      'diperhatikan. Kelas dengan akurasi rendah (Bagian 7) perlu diperiksa ulang sebelum dipakai '
                      'untuk perencanaan.',
        }.get(fit['level_code'],
              'Akurasi peta masih rendah, sehingga peta ini belum disarankan untuk pengambilan keputusan. Gunakan '
              'sebagai bahan eksplorasi, lalu perbaiki data sampel dan parameter mengikuti rekomendasi di Bagian 8.'))
        if fit['flags']:
            self.p('<b>Hal yang perlu diperhatikan pada peta ini:</b>')
            self.bullets([E(f) for f in fit['flags']])
        self.box('Alur laporan',
                 'Laporan mengikuti urutan pembuatan peta di Luma: wilayah dan periode (Bagian 1) → citra satelit (2) '
                 '→ kelas lahan (3) → data sampel (4) → model (5) → hasil peta (6) → akurasi (7) → kelayakan dan '
                 'rekomendasi (8). Istilah teknis dijelaskan di Glosarium (Lampiran C).', 'pink')
        self.add(PageBreak())

    def area_and_period(self):
        a, pe = self.c['aoi'], self.c['period']
        self.h1('1. Wilayah dan Periode Pemetaan')
        text = 'Wilayah pemetaan ditentukan dengan cara {}'.format(a['method_label'])
        if a['method'] == 'admin':
            text += ', yaitu batas administrasi {} dari Badan Informasi Geospasial (BIG){}'.format(
                E(a['admin_name']), self.fn('Batas administrasi kabupaten/kota dari Badan Informasi Geospasial (BIG), '
                                            'disimpan sebagai aset Google Earth Engine.'))
        elif a['method'] == 'upload':
            text += ', menggunakan berkas {}'.format(E(a['file_name'])) if a['file_name'] else ''
        else:
            text += ', dengan menggambar poligon langsung pada peta'
        text += '. Luasnya sekitar {} hektare'.format(a['area_ha'])
        if a['admin_overlap']:
            text += ' dan berada di {}'.format(E(a['admin_overlap']))
        self.p(text + ', dengan titik tengah pada {}.'.format(a['centroid']))
        self.p('Peta dibuat untuk periode {}: citra yang direkam antara {} digabungkan menjadi satu gambaran kondisi '
               'lahan, sehingga perubahan di dalam rentang itu (misalnya panen atau pembukaan lahan) tidak terlihat '
               'tersendiri. Pada resolusi {}, satu piksel mewakili sekitar {} ha; objek yang lebih kecil, seperti jalan '
               'kecil atau rumah, akan tergabung dengan kelas di sekitarnya.'.format(
                   E(pe['period_label']), pe['date_range'], a['resolution_label'], a['pixel_area_ha']))
        self.figure('fig_aoi', 'Gambar 1. Wilayah pemetaan di atas peta dasar')
        rows = [('Cara penentuan wilayah', a['method_label'])]
        if a['admin_overlap']:
            rows.append(('Wilayah administrasi', E(a['admin_overlap'])))
        rows += [('Perkiraan luas', '{} ha'.format(a['area_ha'])),
                 ('Koordinat titik tengah', a['centroid']),
                 ('Resolusi spasial / sistem koordinat', '{} / {}'.format(a['resolution_label'], a['crs'])),
                 ('Jangka waktu / periode', '{} / {}'.format(pe['interval_label'], E(pe['period_label']))),
                 ('Rentang tanggal citra', pe['date_range'])]
        self.kv_table(rows, 'Tabel 1. Informasi dasar pemetaan')
        self.p('Penafian: batas wilayah mengikuti poligon yang dimasukkan pengguna dan belum tentu sama dengan batas '
               'legal, konsesi, atau kelola resmi. Luas bersifat perkiraan.', 'note')

    def imagery(self):
        pe, im, flags = self.c['period'], self.c['imagery'], self.c['flags']
        sentinel = im['sensor'].lower().startswith('sentinel')
        source = ('Citra Sentinel-2 dari program Copernicus (ESA), diakses melalui Google Earth Engine '
                  '(Gorelick dkk., 2017).' if sentinel else
                  'Citra Landsat dari U.S. Geological Survey (USGS), Landsat Collection 2, diakses melalui Google '
                  'Earth Engine (Gorelick dkk., 2017).')
        self.h1('2. Citra Satelit yang Digunakan')
        self.p('Peta dibuat dari citra {}{}. Luma mencari semua citra pada {} dengan tutupan awan paling banyak {}%, '
               'menghapus piksel berawan, lalu menggabungkan sisanya menjadi satu citra komposit yang hampir bebas '
               'awan{}. Sebanyak {} citra memenuhi syarat, dengan rata-rata tutupan awan {}% (terendah {}%, tertinggi '
               '{}%).'.format(E(im['sensor']), self.fn(source), pe['date_range'], im['cloud_max_pct'],
                              self.fn('Penyusunan komposit bebas awan mengikuti Modul 1 Luma Geospatial Engine '
                                      '(Luma Development Reference).'),
                              im['scene_count'], im['cloud_mean'], im['cloud_min'], im['cloud_max']))
        if flags['high_cloud'] or flags['few_scenes']:
            self.box('Perhatian: kualitas citra',
                     ('Jumlah citra sedikit, sehingga celah akibat awan tidak selalu tertutup citra lain. '
                      if flags['few_scenes'] else '')
                     + ('Tutupan awan relatif tinggi. ' if flags['high_cloud'] else '')
                     + 'Area yang sering tertutup awan atau bayangannya dapat berisi data kosong atau nilai kurang '
                       'akurat dan berisiko salah diklasifikasikan.', 'orange')
        self.table('Tabel 2. Citra satelit yang digabungkan',
                   ['No.', 'ID citra', 'Tanggal perekaman', 'Tile' if sentinel else 'Path/Row', 'Awan (%)'],
                   [[s['no'], E(s['scene_id']), s['date'], E(s['path_row']), s['cloud_pct']] for s in im['scenes']],
                   [12, 72, 36, 24, 26], right=(4,))
        self.figure('fig_rgb', 'Gambar 2. Citra komposit warna asli (RGB). Pada komposit warna semu inframerah, '
                               'vegetasi sehat tampak merah dan air tampak gelap.')
        self.figure('fig_fci', 'Gambar 2b. Citra komposit warna semu inframerah (NIR/Red/Green)')

    def scheme(self):
        cl = self.c['classif']
        self.h1('3. Skema Klasifikasi')
        if cl['scheme'] == 'default':
            self.p('Peta ini memakai skema bawaan Epistem, yang diturunkan dari 17 kelas LULC RESTORE+ untuk '
                   'Indonesia{}. Pengguna memilih {} kelas. Karena definisinya baku, hasil peta mudah dibandingkan '
                   'dengan peta lain yang memakai skema sama.'.format(
                       self.fn('Skema 17 kelas LULC RESTORE+ untuk Indonesia, dasar skema bawaan Epistem.'),
                       cl['n_classes']))
        else:
            self.p('Pengguna menyusun skema klasifikasi sendiri yang terdiri atas {} kelas{}. Definisi kelas mengikuti '
                   'pemahaman pengguna; pastikan arti setiap kelas sama sebelum membandingkan peta ini dengan peta '
                   'lain. Lahan yang tidak cocok dengan kelas mana pun tetap akan masuk ke kelas yang paling '
                   'mirip.'.format(cl['n_classes'],
                                   ' (berkas {})'.format(E(cl['file_name'])) if cl['file_name'] else ''))
        self.table('Tabel 3. Kelas penggunaan dan tutupan lahan', ['ID', 'Kelas', 'Warna', 'Kode hex', 'Keterangan'],
                   [[k['id'], E(k['name']), '', '#' + k['hex'], E(k['description'])] for k in cl['classes']],
                   [12, 62, 16, 22, 58], swatch=(2, [k['hex'] for k in cl['classes']]))

    def samples(self):
        c = self.c
        sa, cl, sep, flags = c['sample'], c['classif'], c['separability'], c['flags']
        self.h1('4. Data Sampel')
        self.p('Data sampel adalah lokasi yang kelas lahannya sudah diketahui. Dari lokasi ini model belajar mengenali '
               'tampilan setiap kelas di citra, lalu menerapkannya ke seluruh wilayah; karena itu mutu peta sangat '
               'bergantung pada jumlah, sebaran, dan ketepatan sampel.')
        if sa['source'] == 'default':
            self.p('Peta ini menggunakan data referensi Epistem ({}) yang sudah divalidasi, sehingga pengguna tidak '
                   'menambahkan sampel sendiri. Tersedia {} sampel untuk {} kelas di wilayah ini.'.format(
                       E(sa['ref_dataset_label']), sa['total_samples'], cl['n_classes']))
        else:
            self.p('Data sampel {}{}: {} sampel untuk {} kelas, menghasilkan {} piksel valid.'.format(
                sa['source_label'], ' (berkas {})'.format(E(sa['file_name'])) if sa['file_name'] else '',
                sa['total_samples'], cl['n_classes'], sa['total_pixels']))
        self.figure('fig_samples', 'Gambar 3. Sebaran data sampel')
        self.table('Tabel 4. Data sampel per kelas', ['ID', 'Kelas', 'Warna', 'Jumlah sampel', 'Piksel valid'],
                   [[k['id'], E(k['name']), '', k['n_samples'], k['n_pixels']] for k in sa['per_class']],
                   [12, 86, 16, 28, 28], right=(3, 4), swatch=(2, [k['hex'] for k in sa['per_class']]))
        if not sep:
            return
        self.h2('4.1 Kualitas data sampel')
        self.p('Luma memeriksa apakah setiap pasangan kelas punya karakteristik pantulan cahaya (spektral) yang cukup '
               'berbeda di citra, diukur dengan Transformed Divergence (TD){} bernilai 0–2: semakin mendekati 2, '
               'semakin mudah dua kelas dibedakan. Dari {} pasangan kelas, {} terpisah baik, {} lemah, dan {} buruk '
               '(rata-rata TD {}, kategori {}). Pasangan yang paling sulit dibedakan ditunjukkan pada Tabel 5.'.format(
                   self.fn('Swain &amp; Davis (1978); dihitung dari statistik spektral piksel pada citra komposit '
                           '(Modul 4 Luma Geospatial Engine).'),
                   sep['n_pairs'], sep['n_good'], sep['n_weak'], sep['n_poor'], sep['mean_td'], sep['category_label']))
        self.table('Tabel 5. Pasangan kelas dengan keterpisahan terendah', ['Kelas A', 'Kelas B', 'Nilai TD', 'Kategori'],
                   [[E(x['a']), E(x['b']), x['td'], x['label']] for x in sep['hardest_pairs']],
                   [62, 62, 22, 24], right=(2,))
        if flags['low_pixels']:
            self.box('Perhatian: piksel sampel sangat sedikit',
                     'Kelas berikut memiliki piksel valid sangat sedikit: {}. Nilai keterpisahan yang tinggi pada '
                     'sampel sekecil ini belum tentu mencerminkan kondisi lapangan, dan kelas-kelas ini cenderung '
                     'berakurasi rendah (Bagian 7).'.format(E(sep['low_pixel_classes'])), 'orange')

    def method(self):
        pa = self.c['params']
        self.h1('5. Cara Peta Dibuat')
        if pa['locked']:
            self.p('Karena memakai skema dan sampel bawaan, parameter berikut ditetapkan sistem Luma dan dicatat agar '
                   'peta dapat ditelusuri.')
        self.p('Selain kanal spektral citra, model diberi data tambahan (prediktor) yang membantu membedakan kelas, '
               'seperti indeks vegetasi, indeks air, dan bentuk permukaan bumi{}. Klasifikasi dilakukan dengan Random '
               'Forest{}: {} pohon keputusan masing-masing belajar dari sebagian data sampel, menebak kelas setiap '
               'piksel, dan kelas dengan suara terbanyak menjadi hasil akhir. Sebelum pelatihan, sampel dibagi acak '
               'per kelas: {}% untuk melatih model dan {}% untuk menguji akurasinya (Bagian 7.1).'.format(
                   self.fn('Indeks spektral mengikuti katalog Awesome Spectral Indices (Montero dkk., 2023); topografi '
                           'dari model elevasi digital (NASADEM bawaan, atau Copernicus GLO-30 / ALOS AW3D30).'),
                   self.fn('Breiman (2001); diimplementasikan dengan ee.Classifier.smileRandomForest di Google Earth '
                           'Engine.'),
                   pa['n_trees'], pa['train_pct'], pa['val_pct']))
        self.table('Tabel 6. Prediktor yang digunakan', ['Prediktor', 'Nama lengkap', 'Membantu mengenali', 'Sumber'],
                   [[E(x['code']), E(x['name']), E(x['measures']), E(x['source'])] for x in pa['predictors']],
                   [25, 60, 53, 32])
        self.kv_table([
            ('Metode', 'Random Forest (smileRandomForest, Google Earth Engine)'),
            ('Pohon keputusan / populasi daun minimum', '{} / {}'.format(pa['n_trees'], pa['min_leaf'])),
            ('Pembagian data latih / uji', '{}% / {}% (acak berstrata per kelas)'.format(pa['train_pct'], pa['val_pct'])),
        ], 'Tabel 7. Parameter model', label_mm=72)

    def result(self):
        c = self.c
        a, pe, res = c['aoi'], c['period'], c['result']
        top = res['top']
        self.h1('6. Hasil: Peta Penggunaan dan Tutupan Lahan')
        self.figure('fig_map', 'Gambar 4. Peta penggunaan dan tutupan lahan {}, {}'.format(
            E(a['display_name']), E(pe['period_label'])))
        self.h2('6.1 Komposisi tutupan lahan')
        text = '{} mendominasi wilayah dengan luas sekitar {} ha ({}%), diikuti {} ({} ha; {}%)'.format(
            E(top[0]['name']), top[0]['area_ha'], top[0]['pct'], E(top[1]['name']), top[1]['area_ha'], top[1]['pct'])
        if len(top) > 2:
            text += ' dan {} ({} ha; {}%)'.format(E(top[2]['name']), top[2]['area_ha'], top[2]['pct'])
        text += '. Tiga kelas ini mencakup {}% wilayah.'.format(res['top3_pct'])
        if res['has_veg_split']:
            text += ' Kelas bervegetasi mencakup {}% dan non-vegetasi {}%.'.format(res['veg_pct'], res['nonveg_pct'])
        if res['small_classes']:
            text += (' Kelas yang menempati kurang dari 1% ({}) lebih rentan salah klasifikasi, sehingga luasnya perlu '
                     'ditafsirkan hati-hati.'.format(E(res['small_classes'])))
        self.p(text)
        rows = [[k['rank'], E(k['name']), '', k['area_ha'], k['pct']] for k in res['composition']]
        hexes = [k['hex'] for k in res['composition']] + [None]
        rows.append(['', 'Total terklasifikasi', '', res['total_ha'], '100'])
        if res['nodata_ha']:
            rows.append(['', 'Tidak terklasifikasi (tanpa data, mis. awan)', '', res['nodata_ha'], '–'])
            hexes.append(None)
        self.table('Tabel 8. Luas dan proporsi setiap kelas', ['#', 'Kelas', 'Warna', 'Luas (ha)', 'Proporsi (%)'],
                   rows, [12, 86, 16, 28, 28], right=(3, 4), swatch=(2, hexes))
        if res['nodata_ha']:
            self.p('Proporsi dihitung terhadap luas terklasifikasi. Sekitar {} ha ({}% wilayah) tidak terklasifikasi '
                   'karena tidak memiliki data citra valid.'.format(res['nodata_ha'], res['nodata_pct']), 'note')
        self.figure('fig_composition', 'Gambar 5. Proporsi luas setiap kelas')
        self.p('Catatan: luas dihitung dari jumlah piksel peta dan bersifat perkiraan, karena peta mengandung kesalahan '
               'klasifikasi. Untuk pelaporan yang menuntut ketelitian tinggi (mis. emisi atau klaim karbon), estimasi '
               'ulang luas dengan metode berbasis sampel referensi (Olofsson dkk., 2014).', 'note')

    @staticmethod
    def _confusions(items, unit=''):
        return '; '.join('{} terpetakan sebagai {} ({}{})'.format(E(x['actual']), E(x['predicted']), x['count'], unit)
                         for x in items)

    def accuracy(self):
        c = self.c
        pa, ma, th, flags = c['params'], c['model_acc'], c['thematic'], c['flags']
        self.h1('7. Seberapa Akurat Peta Ini?')
        self.p('Setiap peta hasil klasifikasi citra mengandung kesalahan. Luma menyediakan dua jenis pengujian: akurasi '
               'model memakai {}% sampel yang disisihkan sebelum pelatihan dan cenderung optimis bila sampel sedikit; '
               'akurasi tematik memakai data validasi independen dari pengguna dan lebih mencerminkan kesesuaian peta '
               'dengan kondisi lapangan.'.format(pa['val_pct']))
        self.box('Cara membaca angka akurasi',
                 '<b>Akurasi keseluruhan (OA):</b> persentase lokasi uji yang kelasnya benar. <b>Kappa:</b> kesesuaian '
                 'setelah dikurangi peluang benar secara kebetulan (0 = setara tebakan acak, mendekati 1 = sangat '
                 'baik){}.<br/><b>PA (producer\'s accuracy):</b> seberapa sering kelas X di lapangan terpetakan sebagai '
                 'X. <b>UA (user\'s accuracy):</b> seberapa sering piksel X di peta memang X. <b>F1 dan G-mean</b> '
                 'merangkum keduanya.<br/><b>Kategori:</b> tinggi bila OA ≥ 85%, sedang 70–85%, rendah di bawah '
                 '70%.{}'.format(self.fn('Cohen (1960); interpretasi mengacu pada Landis &amp; Koch (1977).'),
                                 self.fn('Ambang 85% mengacu pada Anderson dkk. (1976). Ambang dapat disesuaikan '
                                         'dengan kebutuhan program.')), 'pink')
        self.h2('7.1 Akurasi model')
        self.cards([('Akurasi keseluruhan', '{}%'.format(ma['oa']), 'Kategori {}'.format(ma['level_label'])),
                    ('Koefisien kappa', ma['kappa'], ''), ('Rata-rata skor F1', ma['f1'], ''),
                    ('G-mean', ma['gmean'], '')])
        text = 'Model diuji dengan {} sampel yang tidak dipakai saat pelatihan: {}% terklasifikasi benar, dengan kappa {}.'.format(
            ma['n_val_samples'], ma['oa'], ma['kappa'])
        if ma['confusions']:
            text += ' Kesalahan tersering: {}.'.format(self._confusions(ma['confusions']))
        self.p(text)
        if flags['small_val']:
            self.box('Perhatian: sampel uji terlalu sedikit',
                     'Hanya {} sampel uji, sehingga beberapa kelas diuji dengan satu sampel atau tidak sama sekali. '
                     'Satu kesalahan dapat mengubah akurasi secara drastis; angka ini belum stabil dan belum dapat '
                     'dijadikan ukuran mutu peta.'.format(ma['n_val_samples']), 'orange')
        self.table('Tabel 9a. Akurasi model per kelas', ['Kelas', 'Sampel uji', 'PA (%)', 'UA (%)', 'F1'],
                   [[E(k['name']), k['n'], k['pa'], k['ua'], k['f1']] for k in ma['classes']],
                   [78, 23, 23, 23, 23], right=(1, 2, 3, 4))
        self.figure('fig_cm_model', 'Gambar 6. Matriks kesalahan akurasi model (baris: kelas sebenarnya, kolom: '
                                    'kelas prediksi)')
        self.h2('7.2 Akurasi tematik peta')
        if not th['done']:
            self.box('Akurasi tematik belum diuji',
                     'Kesesuaian peta dengan kondisi lapangan belum diketahui, dan akurasi model di Bagian 7.1 belum '
                     'cukup untuk menggantikannya. Kumpulkan titik validasi di lapangan atau dari citra resolusi '
                     'tinggi yang tidak dipakai sebagai sampel, lalu unggah di langkah Akurasi Tematik pada Luma.',
                     'orange')
            return
        text = ('Akurasi tematik diuji dengan {} titik validasi independen{}. Sebanyak {} titik sesuai dan {} tidak '
                'sesuai, sehingga akurasi keseluruhan {}% (kategori {}, kappa {}). Selang kepercayaan 95% sebesar {} '
                'berarti akurasi sebenarnya kemungkinan besar berada di rentang tersebut.'.format(
                    th['n_points'], self.fn('Mengikuti kerangka Olofsson dkk. (2014) dan Congalton (1991); selang '
                                            'kepercayaan dengan pendekatan normal.'),
                    th['n_correct'], th['n_wrong'], th['oa'], th['level_label'], th['kappa'], th['ci']))
        if th['confusions']:
            text += ' Kesalahan tersering: {}.'.format(self._confusions(th['confusions'], ' titik'))
        self.p(text)
        self.cards([('Akurasi keseluruhan', '{}%'.format(th['oa']), 'SK 95%: {}'.format(th['ci'])),
                    ('Koefisien kappa', th['kappa'], ''),
                    ('Titik benar / salah', '{} / {}'.format(th['n_correct'], th['n_wrong']),
                     'dari {} titik'.format(th['n_points'])),
                    ('Tingkat kesalahan', '{}%'.format(th['error_rate']), '')])
        self.table('Tabel 9b. Akurasi tematik per kelas', ['Kelas', 'Titik validasi', 'PA (%)', 'UA (%)', 'F1'],
                   [[E(k['name']), k['n'], k['pa'], k['ua'], k['f1']] for k in th['classes']],
                   [78, 23, 23, 23, 23], right=(1, 2, 3, 4))
        self.figure('fig_cm_thematic', 'Gambar 7. Matriks kesalahan akurasi tematik')
        self.figure('fig_val_points', 'Gambar 8. Sebaran titik validasi: hijau = sesuai, merah = tidak sesuai')
        self.p('Penafian: hasil pengujian hanya sebaik data validasinya. Data validasi harus terpisah dari data sampel, '
               'tersebar mewakili seluruh wilayah dan kelas, serta diperiksa ketepatannya.', 'note')

    def interpretation(self):
        fit = self.c['fitness']
        self.h1('8. Interpretasi dan Rekomendasi')
        self.h2('8.1 Untuk apa peta ini layak dipakai?')
        self.p('Berdasarkan akurasi dan kondisi data, tingkat keyakinan peta ini adalah {}. Tabel berikut memberi '
               'panduan umum kesesuaiannya.'.format(fit['level_label']))
        self.table('Tabel 10. Kesesuaian penggunaan peta', ['Keperluan', 'Kesesuaian', 'Catatan'],
                   [[E(u['use']), E(u['status']), E(u['note'])] for u in fit['uses']], [63, 32, 75])
        self.h2('8.2 Keterbatasan')
        self.p('Selain hal khusus pada Ringkasan, keterbatasan berikut berlaku untuk semua peta Luma: peta '
               'menggambarkan kondisi rata-rata selama periode citra; objek yang lebih kecil dari piksel dan piksel di '
               'perbatasan kelas bisa tercampur; kelas yang mirip di citra (misalnya beberapa jenis kebun dan hutan '
               'sekunder) mudah tertukar; dan akurasi sangat bergantung pada mutu, jumlah, dan sebaran data sampel.')
        self.h2('8.3 Langkah berikutnya')
        self.bullets([E(x) for x in fit['recommendations']], numbered=True)

    def disclaimer(self):
        self.h1('9. Penafian')
        self.p('Laporan dan peta ini dihasilkan otomatis oleh Luma (inisiatif Epistem) dari masukan pengguna, yang '
               'kebenarannya tidak diverifikasi oleh konsorsium Epistem. Dengan menggunakan laporan ini, pembaca '
               'memahami bahwa:')
        self.bullets([
            'Peta adalah hasil pemodelan statistik dan memiliki ketidakpastian; akurasi yang dilaporkan berlaku untuk '
            'data uji yang digunakan, bukan jaminan ketepatan di setiap lokasi.',
            'Laporan ini bukan peta resmi, tidak menggantikan data instansi pemerintah yang berwenang, dan batas '
            'wilayahnya tidak memiliki kekuatan hukum.',
            'Jangan mengandalkan dokumen ini sebagai satu-satunya dasar keputusan hukum, perizinan, sengketa lahan, '
            'keuangan, sertifikasi, atau klaim karbon. Verifikasi dengan data lapangan, sumber resmi, dan penilaian '
            'ahli.',
            'Data pihak ketiga (citra satelit, model elevasi, batas administrasi) tunduk pada lisensi penyedianya. '
            'Laporan disediakan "sebagaimana adanya"; konsorsium Epistem dan mitranya tidak bertanggung jawab atas '
            'kerugian akibat penggunaannya.',
        ], numbered=True)

    def appendix(self):
        c = self.c
        r, a, pe, im, cl, sa, pa, th = (c['report'], c['aoi'], c['period'], c['imagery'], c['classif'], c['sample'],
                                        c['params'], c['thematic'])
        self.h1('Lampiran')
        self.h2('A. Metadata dan keterlacakan')
        validation = 'Tidak ada'
        if th['done']:
            validation = '{} titik'.format(th['n_points'])
            if th['file_name']:
                validation = '{} ({})'.format(E(th['file_name']), validation)
        self.kv_table([
            ('Nama peta', E(r['map_name'])),
            ('ID Proyek / ID Sesi', '{} / {}'.format(E(r['project_id']), E(r['session_id']))),
            ('Waktu pembuatan peta', r['generated_at']),
            ('Versi Luma / Geospatial Engine', '{} / {}'.format(E(r['luma_version']), E(r['ge_version']))),
            ('Wilayah', '{} · {} · {} ha · {} · {}'.format(a['method_label'], E(a['display_name']), a['area_ha'],
                                                         a['crs'], a['resolution_label'])),
            ('Citra', '{} · {} · awan maks. {}% · {} citra'.format(pe['date_range'], E(im['sensor']),
                                                                 im['cloud_max_pct'], im['scene_count'])),
            ('Skema / sampel', '{} ({} kelas) · {} sampel{}'.format(
                cl['scheme_label'], cl['n_classes'], sa['total_samples'],
                ' · ' + E(sa['ref_dataset_label']) if sa['ref_dataset_label'] else '')),
            ('Prediktor / model', '{} · RF {} pohon, daun min. {}, latih/uji {}/{}'.format(
                E(pa['predictor_codes']), pa['n_trees'], pa['min_leaf'], pa['train_pct'], pa['val_pct'])),
            ('Data validasi tematik', validation),
            ('Tautan peta', E(r['map_url'])),
        ])
        self.h2('B. Cara mengutip')
        self.box('', '{} ({}). {}: Peta Penggunaan dan Tutupan Lahan {}, {}. Dibuat dengan Luma {}, Epistem. ID Sesi '
                     '{}.'.format(E(r['prepared_by']), r['issued_year'], E(r['map_name']), E(a['display_name']),
                                  E(pe['period_label']), E(r['luma_version']), E(r['session_id'])), 'pink')
        self.h2('C. Glosarium')
        self.table(None, ['Istilah', 'Arti'], [list(row) for row in GLOSSARY], [50, 120])
        self.h2('D. Daftar pustaka dan sumber data')
        for ref in list(REFERENCES) + [E(x) for x in c['extra_references']]:
            self.p(ref, 'ref')

    def build(self):
        for part in (self.cover, self.contents, self.summary, self.area_and_period, self.imagery, self.scheme,
                     self.samples, self.method, self.result, self.accuracy, self.interpretation, self.disclaimer,
                     self.appendix):
            part()
        self.flush_notes()
        return self.story


def build_pdf(context, figures):
    """
    context: the fields from context.build_context.
    figures: {'fig_map': {'image': bytes, 'width_mm': 96} or None, ...} from builder.build_figures.
    Returns the report as PDF bytes.
    """
    _register_fonts()
    report = _Report(context, figures)
    r, pe = context['report'], context['period']
    header = '{}  ·  {}'.format(r['map_name'], pe['period_label'])
    footer = 'Luma · Epistem  |  ID Sesi {}  |  Laporan dibuat otomatis, bukan peta resmi'.format(r['session_id'])
    target = io.BytesIO()
    doc = _Doc(target, header, footer, report.draw_cover_block)
    doc.multiBuild(report.build() + [_PageCount(doc)])
    return target.getvalue()
