"""Fills the Word template of the map report and tidies the result for conversion to PDF."""
import io
import logging
import os
import pathlib
import re
import shutil
import subprocess
import zipfile
from xml.sax.saxutils import escape as xml_escape

from docx.shared import Mm
from docxtpl import DocxTemplate, InlineImage
from jinja2 import Environment, StrictUndefined
from lxml import etree

logger = logging.getLogger(__name__)

W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
FOOTNOTES_PART = 'word/footnotes.xml'
DOCUMENT_PART = 'word/document.xml'


def fill_template(template_path, context, figures, out_path):
    """
    figures: {'fig_map': {'image': bytes, 'width_mm': 110} or None, ...}
    A missing template field raises instead of printing an empty string.
    Returns the ids of the footnotes that were dropped (see drop_orphan_footnotes).
    """
    tpl = DocxTemplate(template_path)
    ctx = dict(context)
    for name, fig in figures.items():
        ctx[name] = InlineImage(tpl, io.BytesIO(fig['image']), width=Mm(fig['width_mm'])) if fig else None
    tpl.render(ctx, jinja_env=Environment(undefined=StrictUndefined), autoescape=True)
    tpl.save(out_path)
    return drop_orphan_footnotes(out_path)


def drop_orphan_footnotes(docx_path):
    """
    Two of the template's footnotes sit inside optional blocks. When a block is
    left out, its reference disappears but its text stays in footnotes.xml, and
    the PDF converter then hands the texts out in order -- every later footnote
    shows the wrong text. Removing the unreferenced footnotes keeps them aligned.
    """
    with zipfile.ZipFile(docx_path) as z:
        entries = [(info, z.read(info.filename)) for info in z.infolist()]
    parts = {info.filename: data for info, data in entries}
    if FOOTNOTES_PART not in parts:
        return []

    used = {m.decode() for m in re.findall(rb'<w:footnoteReference\b[^>]*w:id="(-?\d+)"', parts[DOCUMENT_PART])}
    root = etree.fromstring(parts[FOOTNOTES_PART])
    removed = []
    for footnote in root.findall('{%s}footnote' % W_NS):
        if footnote.get('{%s}type' % W_NS):  # separator / continuationSeparator
            continue
        fid = footnote.get('{%s}id' % W_NS)
        if fid not in used:
            root.remove(footnote)
            removed.append(fid)
    if not removed:
        return []

    parts[FOOTNOTES_PART] = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
    with zipfile.ZipFile(docx_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for info, _data in entries:
            z.writestr(info, parts[info.filename])
    return removed


SOFFICE_CANDIDATES = (
    r'C:\Program Files\LibreOffice\program\soffice.exe',
    r'C:\Program Files (x86)\LibreOffice\program\soffice.exe',
    '/usr/bin/soffice',
    '/Applications/LibreOffice.app/Contents/MacOS/soffice',
)


def find_soffice():
    """LibreOffice's program: SOFFICE_PATH if set, then PATH, then the usual install folders. None if absent."""
    configured = os.environ.get('SOFFICE_PATH')
    if configured:
        return configured if os.path.isfile(configured) else None
    return shutil.which('soffice') or next((c for c in SOFFICE_CANDIDATES if os.path.isfile(c)), None)


# A plain "--convert-to pdf" leaves the table of contents empty, so LibreOffice
# runs this macro instead: open the .docx, refresh every index (twice, in case
# the first pass moved a page break), export the PDF. Paths come in through the
# environment so nothing has to be quoted on the command line.
_PDF_MACRO = '\n'.join([
    'Sub ToPdf',
    '    Dim oDoc As Object, oIndexes As Object, i As Integer, n As Integer',
    '    Dim aLoad(0) As New com.sun.star.beans.PropertyValue',
    '    Dim aStore(0) As New com.sun.star.beans.PropertyValue',
    '    On Error GoTo Done',
    '    aLoad(0).Name = "Hidden"',
    '    aLoad(0).Value = True',
    '    oDoc = StarDesktop.loadComponentFromURL(ConvertToURL(Environ("LUMA_REPORT_DOCX")), "_blank", 0, aLoad())',
    '    oIndexes = oDoc.getDocumentIndexes()',
    '    For n = 1 To 2',
    '        For i = 0 To oIndexes.getCount() - 1',
    '            oIndexes.getByIndex(i).update()',
    '        Next i',
    '    Next n',
    '    aStore(0).Name = "FilterName"',
    '    aStore(0).Value = "writer_pdf_Export"',
    '    oDoc.storeToURL(ConvertToURL(Environ("LUMA_REPORT_PDF")), aStore())',
    '    oDoc.close(True)',
    'Done:',
    '    If Err <> 0 Then',
    '        n = FreeFile',
    '        Open Environ("LUMA_REPORT_PDF") & ".err" For Output As #n',
    '        Print #n, "error " & Err & " at line " & Erl & ": " & Error$',
    '        Close #n',
    '    End If',
    '    StarDesktop.terminate()',
    'End Sub',
    '',
])
_BASIC_LIBRARY = '\n'.join([
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<!DOCTYPE library:library PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "library.dtd">',
    '<library:library xmlns:library="http://openoffice.org/2000/library" library:name="Standard" '
    'library:readonly="false" library:passwordprotected="false">',
    ' <library:element library:name="Module1"/>',
    ' <library:element library:name="Report"/>',
    '</library:library>',
    '',
])
_BASIC_MODULE = '\n'.join([
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<!DOCTYPE script:module PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "module.dtd">',
    '<script:module xmlns:script="http://openoffice.org/2000/script" script:name="Report" '
    'script:language="StarBasic">{code}</script:module>',
    '',
])


def _add_pdf_macro(profile_dir):
    standard = os.path.join(profile_dir, 'user', 'basic', 'Standard')
    os.makedirs(standard, exist_ok=True)
    with open(os.path.join(standard, 'script.xlb'), 'w', encoding='utf-8') as f:
        f.write(_BASIC_LIBRARY)
    with open(os.path.join(standard, 'Report.xba'), 'w', encoding='utf-8') as f:
        f.write(_BASIC_MODULE.format(code=xml_escape(_PDF_MACRO, {'"': '&quot;'})))


def docx_to_pdf(docx_path, out_dir, soffice, timeout=180):
    """
    Converts with LibreOffice (the tool that made the example PDF) and returns
    the PDF's path, with the table of contents filled in.

    Each call gets its own LibreOffice profile folder inside out_dir, so
    conversions running at the same time, or a LibreOffice window the user has
    open, cannot get in each other's way.
    """
    profile = pathlib.Path(out_dir, 'lo_profile').resolve()
    base = [soffice, '-env:UserInstallation=' + profile.as_uri(), '--headless', '--norestore', '--nologo']
    quiet = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
    pdf_path = os.path.splitext(os.path.join(out_dir, os.path.basename(docx_path)))[0] + '.pdf'

    # LibreOffice rewrites user/basic the first time a profile starts, so start
    # it once, then add the macro, then run the macro.
    try:
        subprocess.run(base + ['--terminate_after_init'], timeout=timeout, **quiet)
        _add_pdf_macro(str(profile))
        env = dict(os.environ, LUMA_REPORT_DOCX=os.path.abspath(docx_path), LUMA_REPORT_PDF=os.path.abspath(pdf_path))
        subprocess.run(base + ['macro:///Standard.Report.ToPdf'], env=env, timeout=timeout, **quiet)
    except (OSError, subprocess.SubprocessError) as e:
        logger.error('report: PDF macro run failed: {}'.format(e))
    if os.path.isfile(pdf_path):
        return pdf_path

    # Better a PDF with an empty table of contents than no PDF.
    reason = ''
    if os.path.isfile(pdf_path + '.err'):
        with open(pdf_path + '.err', encoding='utf-8', errors='replace') as f:
            reason = f.read().strip()
    logger.warning('report: table of contents not refreshed, using plain conversion. {}'.format(reason))
    subprocess.run(base + ['--convert-to', 'pdf', '--outdir', out_dir, docx_path],
                   check=True, timeout=timeout, **quiet)
    if not os.path.isfile(pdf_path):
        raise RuntimeError('LibreOffice did not produce a PDF for {}'.format(os.path.basename(docx_path)))
    return pdf_path
