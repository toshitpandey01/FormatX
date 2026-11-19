import csv
from dataclasses import dataclass
from html import escape
import os
from pathlib import Path
import shutil
import time
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

from PIL import Image, ImageOps
import pymupdf as pdf
from .validation import IMAGE, OFFICE, MAX_PAGES, Problem, open_pdf, page_numbers

ROOT = Path(__file__).resolve().parent.parent

@dataclass
class Result:
    path: Path
    suffix: str
    notice: str = ''
    original_size: int = 0
    page_count: int = 0


def engine(program):
    executable = shutil.which(program)
    if not executable:
        raise Problem(f'{program} is not installed. See the setup guide for this conversion.', 503)
    return executable


def run(command, work, timeout=None):
    limit = timeout or int(os.getenv('FORMATX_ENGINE_TIMEOUT', '120'))
    env = {**os.environ, 'TMPDIR': str(work), 'TEMP': str(work), 'TMP': str(work)}
    try:
        subprocess.run([str(x) for x in command], cwd=work, env=env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=limit)
    except subprocess.TimeoutExpired as exc:
        raise Problem('Processing timed out. Try a smaller document or page range.', 422) from exc
    except (subprocess.CalledProcessError, OSError) as exc:
        raise Problem('The conversion engine could not process this document. Check that it opens normally and try again.', 422) from exc


def office_pdf(source, work):
    target = work / (source.stem + '.pdf')
    run([engine(os.getenv('FORMATX_SOFFICE','libreoffice')), '-env:UserInstallation=' + (work/'office-profile').as_uri(),
         '--headless', '--nologo', '--norestore', '--convert-to', 'pdf', '--outdir', work, source], work)
    if not target.is_file():
        raise Problem('LibreOffice did not produce a PDF. Check the file and try again.', 422)
    return target


def worker(mode, source, target, work):
    run([sys.executable, ROOT/'formatx'/'worker.py', mode, source, target], work)


def output_pdf(doc, path):
    doc.save(path, garbage=3, deflate=True, use_objstms=1, encryption=pdf.PDF_ENCRYPT_NONE)


def as_pdf(path, work, password=''):
    ext = path.suffix
    if ext == '.pdf':
        return path
    if ext in {'.docx','.xlsx','.pptx'}:
        return office_pdf(path, work)
    if ext in {'.html','.htm','.txt'}:
        source = path
        if ext == '.txt':
            source = work/'text-source.html'
            text = escape(path.read_text(encoding='utf-8-sig'))
            source.write_text('<meta charset=utf-8><style>pre{white-space:pre-wrap;overflow-wrap:anywhere;font:11pt monospace}</style><pre>'+text+'</pre>', encoding='utf-8')
        output = work/'rendered.pdf'
        worker('html', source, output, work)
        return output
    if ext in IMAGE:
        output = work/'images.pdf'
        images_to_pdf([path], output)
        return output
    raise Problem('This file cannot be rendered as a PDF.')


def images_to_pdf(paths, output):
    with pdf.open() as doc:
        from io import BytesIO
        for path in paths:
            with Image.open(path) as original:
                im = ImageOps.exif_transpose(original)
                im.thumbnail((4500, 4500))
                im = im.convert('RGBA' if 'A' in im.getbands() or 'transparency' in im.info else 'RGB')
                bw,bh = (842,595) if im.width > im.height else (595,842)
                scale = min((bw-48)/im.width, (bh-48)/im.height)
                w,h = im.width*scale, im.height*scale
                data = BytesIO()
                im.save(data, format='JPEG' if path.suffix in {'.jpg','.jpeg'} else 'PNG', quality=94)
                page = doc.new_page(width=bw,height=bh)
                page.insert_image(pdf.Rect((bw-w)/2,(bh-h)/2,(bw+w)/2,(bh+h)/2),stream=data.getvalue())
        output_pdf(doc,output)


def pixmap(page, dpi, pixel_cap=12_000_000):
    from math import sqrt
    rect = page.rect
    if min(rect.width, rect.height) <= 0:
        raise Problem('A PDF page has invalid dimensions.', 422)
    scale = min(dpi/72, sqrt(pixel_cap/(rect.width * rect.height)), 5000/max(rect.width,rect.height))
    return page.get_pixmap(matrix=pdf.Matrix(scale,scale), alpha=False)


def scanned_pages(doc):
    return [p.number for p in doc if not p.get_text().strip() and (p.get_images() or p.get_image_info())]


def place_ocr_text(surface, raster_size, tsv):
    """Rebuild visible, selectable text at Tesseract's line coordinates."""
    lines = {}
    with tsv.open(encoding='utf-8', newline='') as source:
        for row in csv.DictReader(source, delimiter='\t'):
            word = (row.get('text') or '').strip()
            if row.get('level') == '5' and word:
                key = tuple(row[k] for k in ('block_num','par_num','line_num'))
                bounds = tuple(int(row[k]) for k in ('left','top','width','height'))
                lines.setdefault(key, []).append((word, *bounds))
    sx, sy = surface.rect.width / raster_size[0], surface.rect.height / raster_size[1]
    placed = 0
    for words in lines.values():
        x = min(w[1] for w in words) * sx
        y = min(w[2] for w in words) * sy
        width = (max(w[1]+w[3] for w in words) - min(w[1] for w in words)) * sx
        height = (max(w[2]+w[4] for w in words) - min(w[2] for w in words)) * sy
        text = ' '.join(w[0] for w in words)
        rect = pdf.Rect(x, max(0,y-.18*height), min(surface.rect.width,x+width+1.2*height),
                        min(surface.rect.height,y+1.7*height))
        if not rect.is_empty:
            spare, _ = surface.insert_htmlbox(rect, escape(text),
                css=f'* {{font-family:sans-serif;font-size:{max(3,height*.95):.2f}pt;margin:0;white-space:nowrap}}')
            placed += spare >= 0
    return placed


def has_decoration(page):

    if not page.get_text().strip():
        return False
    rect = page.rect
    if rect.width <= 0 or rect.height <= 0:
        return False
    def inked(d):
        fill = d.get('fill')
        return d.get('color') is not None or (fill is not None and tuple(fill) != (1, 1, 1))
    # A frame may be stroked lines or filled shapes (Word borders export as filled shapes).
    frame = any(d['rect'].width >= .8*rect.width and d['rect'].height >= .8*rect.height and inked(d)
                for d in page.get_drawings())
    flipped = False
    for info in page.get_image_info():
        a, b, c, d, _, _ = info['transform']
        if abs(b) > 1e-3 or abs(c) > 1e-3 or a < 0 or d < 0:
            flipped = True
            break
    if not (frame or flipped):
        return False
    return not page.find_tables().tables


def save_backdrop(source, page_number, work, name):
    """Render only the graphics (images and vector art, no text) of one page."""
    with pdf.open() as single:
        single.insert_pdf(source, from_page=page_number, to_page=page_number, links=False, widgets=False)
        page = single[0]
        page.add_redact_annot(page.rect, fill=False)
        page.apply_redactions(images=pdf.PDF_REDACT_IMAGE_NONE, graphics=pdf.PDF_REDACT_LINE_ART_NONE,
                              text=pdf.PDF_REDACT_TEXT_REMOVE)
        pix = pixmap(page, 200, 16_000_000)
        path = work/f'{name}.png'
        pix.save(path)
        if path.stat().st_size > 1_500_000:  # photo-heavy art compresses far better as JPEG
            path.unlink()
            path = work/f'{name}.jpg'
            path.write_bytes(pix.tobytes('jpeg', jpg_quality=90))
        return path, page.rect.width, page.rect.height


def strip_graphics(page):
    """Leave only the text so pdf2docx does not duplicate (or mangle) the art kept in the backdrop."""
    page.add_redact_annot(page.rect, fill=False)
    page.apply_redactions(images=pdf.PDF_REDACT_IMAGE_REMOVE, graphics=pdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                          text=pdf.PDF_REDACT_TEXT_NONE)


def stack_floating_images(document):

    ns = {'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'}
    anchors = document.element.body.findall('.//wp:anchor', ns)

    def area(anchor):
        extent = anchor.find('wp:extent', ns)
        return int(extent.get('cx', 0)) * int(extent.get('cy', 0)) if extent is not None else 0
    for rank, anchor in enumerate(sorted(anchors, key=area, reverse=True)):
        anchor.set('relativeHeight', str(251658240 + rank))
    return len(anchors)


def add_backdrops(docx_path, backdrops, page_count):
    """Finish a pdf2docx result: restore page art and fix picture stacking. Returns pages restored."""
    from docx import Document
    document = Document(docx_path)
    restored = place_backdrops(document, backdrops, page_count)
    stack_floating_images(document)
    document.save(docx_path)
    return restored


def place_backdrops(document, backdrops, page_count):

    from docx.oxml import parse_xml
    from docx.shared import Emu, Pt
    sections = document.sections
    if not backdrops or len(sections) != page_count:
        return 0
    wp = 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
    # Headers are inherited from the previous section by default, so give every page its own
    # (empty unless it has art) header or the art would repeat on the pages that follow.
    for section in sections:
        section.header.is_linked_to_previous = False
    for number, (path, width, height) in backdrops.items():
        section = sections[number]
        section.header_distance = 0
        header = section.header
        header.is_linked_to_previous = False
        paragraph = header.paragraphs[0]
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.line_spacing = Pt(1)
        run = paragraph.add_run()
        run.font.size = Pt(1)
        cx, cy = int(width*12700), int(height*12700)
        inline = run.add_picture(str(path), width=Emu(cx), height=Emu(cy))._inline
        anchor = parse_xml(
            f'<wp:anchor xmlns:wp="{wp}" distT="0" distB="0" distL="0" distR="0" simplePos="0" '
            f'relativeHeight="0" behindDoc="1" locked="1" layoutInCell="1" allowOverlap="1">'
            f'<wp:simplePos x="0" y="0"/>'
            f'<wp:positionH relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionH>'
            f'<wp:positionV relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionV>'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
            f'<wp:docPr id="{9000+number}" name="Page artwork {number+1}"/><wp:cNvGraphicFramePr/></wp:anchor>')
        anchor.append(inline.graphic)
        drawing = inline.getparent()
        drawing.remove(inline)
        drawing.append(anchor)
    return len(backdrops)


def prepare_pdf(doc, work, use_ocr, lang):
    scans = set(scanned_pages(doc)) if use_ocr else set()
    if len(scans) > 40:
        raise Problem('OCR is limited to 40 scanned pages per job. Split large scans first.', 413)
    prepared = work/'prepared.pdf'
    ocr_deadline = time.monotonic() + 180
    recognized_pages = 0
    backdrops = {}
    with pdf.open() as combined:
        for page in doc:
            if page.number not in scans:
                combined.insert_pdf(doc, from_page=page.number, to_page=page.number, links=False, widgets=False)
                if has_decoration(page):
                    backdrops[page.number] = save_backdrop(doc, page.number, work, f'backdrop-{page.number}')
                    strip_graphics(combined[combined.page_count-1])
            else:
                prefix = work/'ocr-page'
                raster = work/'ocr-page.png'
                pixels = pixmap(page, 180)
                pixels.set_dpi(180,180)
                pixels.save(raster)
                remaining = ocr_deadline - time.monotonic()
                if remaining <= 0:
                    raise Problem('OCR timed out. Split the PDF and try a smaller batch.', 422)
                run([engine('tesseract'), raster, prefix, '-l', lang, 'tsv'], work, timeout=min(40, remaining))
                surface = combined.new_page(width=page.rect.width,height=page.rect.height)
                tsv = prefix.with_suffix('.tsv')
                if place_ocr_text(surface,(pixels.width,pixels.height),tsv):
                    recognized_pages += 1
                else:
                    combined.delete_page(-1)
                    combined.insert_pdf(doc,from_page=page.number,to_page=page.number,links=False,widgets=False)
                tsv.unlink()
        output_pdf(combined, prepared)
    return prepared, len(scans), recognized_pages, backdrops, len(doc)


def tables_to_xlsx(doc, output):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    book = Workbook(); book.remove(book.active)
    for page in doc:
        # Vector rules are more dependable than interpreting arbitrary aligned text as data.
        if not page.get_text().strip():
            continue
        for i, table in enumerate(page.find_tables().tables, 1):
            if len(book.worksheets) >= 100:
                raise Problem('More than 100 tables were found. Split the PDF and convert in batches.', 413)
            sheet = book.create_sheet(f'Page {page.number+1} Table {i}')
            for r, row in enumerate(table.extract(), 1):
                for c, value in enumerate(row, 1):
                    cell = sheet.cell(r,c,value or '')
                    cell.data_type = 's'  # Never turn text taken from documents into formulas.
                    if r == 1:
                        cell.font = Font(bold=True, color='FFFFFF')
                        cell.fill = PatternFill('solid',fgColor='386C88')
            sheet.freeze_panes = 'A2'
    if not book.worksheets:
        raise Problem('No ruled, selectable-text tables were detected. Scanned or unruled tables are not supported by PDF to Excel.', 422)
    book.save(output)


def process(action, paths, data, work):
    first = paths[0]; ext = first.suffix
    password = data.get('password','')
    lang = data.get('lang','eng')
    if lang not in {'eng','fra','deu','spa','chi_sim','chi_tra','jpn','kor'}:
        raise Problem('Select a supported OCR language.')
    if action not in {'merge','images'} and len(paths) != 1:
        raise Problem('This tool accepts exactly one file.')
    if action == 'convert':
        target = data.get('target','')
        if target == 'pdf' and ext != '.pdf':
            path = as_pdf(first,work)
            with open_pdf(path): pass
            notice = ''
            if ext in {'.docx','.xlsx','.pptx'}:
                notice = 'Office layouts can shift if the original fonts are missing. Check pagination and charts.'
            if ext in {'.html','.htm'}:
                notice = 'Print CSS and inline PNG/JPEG images are supported; external assets and interactive content are omitted.'
            return Result(path,'converted.pdf', notice)
        if target == 'txt' and ext == '.docx':
            out = work/'output.txt'
            run([engine('java'), '-Xmx256m', ROOT/'java'/'WordText.java', first, out],work)
            return Result(out,'converted.txt','Plain text from the main document body; images, styling and headers/footers are not included.')
        if ext != '.pdf' or target not in {'docx','xlsx','png','jpg'}:
            raise Problem('This input and output combination is not supported.')
        with open_pdf(first,password) as doc:
            if target in {'png','jpg'}:
                selected = page_numbers(data['pages'],len(doc)) if data.get('pages','').strip() else list(range(len(doc)))
                if len(selected) > 100:
                    raise Problem('Render at most 100 pages at a time. Enter a page range.', 413)
                fmt = 'png' if target == 'png' else 'jpeg'
                if len(selected) == 1:
                    out = work/f'page.{target}'
                    out.write_bytes(pixmap(doc[selected[0]],150).tobytes(fmt))
                    return Result(out,f'page-{selected[0]+1:03}.{target}')
                out = work/'pages.zip'
                with ZipFile(out,'w',ZIP_DEFLATED,compresslevel=1) as bundle:
                    for index, p in enumerate(selected,1):
                        bundle.writestr(f'{index:03}-page-{p+1:03}.{target}',pixmap(doc[p],150).tobytes(fmt))
                        if bundle.fp.tell() > 120 * 1024**2:
                            raise Problem('This image archive is too large. Select fewer pages.', 413)
                return Result(out,'images.zip',f'{len(selected)} images packaged in one ZIP.')
            if target == 'xlsx':
                out = work/'tables.xlsx'; tables_to_xlsx(doc,out)
                return Result(out,'tables.xlsx','Extracted detectable ruled tables only. Check cell boundaries and numeric values; values are exported as text.')
            if len(doc) > 80:
                raise Problem('PDF to Word is limited to 80 pages per job. Split the PDF first.', 413)
            prepared, ocr_count, recognized, backdrops, total = prepare_pdf(doc,work,data.get('ocr')=='1',lang)
        out = work/'converted.docx'; worker('docx',prepared,out,work)
        restored = add_backdrops(out, backdrops, total)
        from docx import Document
        Document(out)
        art = f' Borders, ornaments and logos on {restored} page(s) are kept as a fixed page background behind the editable text.' if restored else ''
        return Result(out,'converted.docx', 'PDF layout is reconstructed; review headings, tables and image positioning.' + art + (f' OCR recovered text on {recognized} of {ocr_count} scanned page(s). On recovered pages, graphics and the original scan background are omitted. Review recognition accuracy.' if ocr_count else ' If the source is scanned, use the OCR option.'))
    if action == 'images':
        if any(p.suffix not in IMAGE for p in paths):
            raise Problem('Image to PDF accepts only JPG and PNG files.')
        output = work/'images.pdf'; images_to_pdf(paths,output)
        return Result(output,'images.pdf', 'Images fit to portrait or landscape A4, preserving their aspect ratios.')
    if action == 'merge':
        if len(paths) < 2:
            raise Problem('Choose at least two documents to merge.')
        if not (all(p.suffix == '.pdf' for p in paths) or all(p.suffix == '.docx' for p in paths)):
            raise Problem('Choose either all PDF files or all DOCX files, not a mix.')
        if ext == '.docx':
            from docx import Document
            from docxcompose.composer import Composer
            out = work/'combined.docx'; base = Document(first); composer = Composer(base)
            for path in paths[1:]:
                base.add_page_break()
                composer.append(Document(path))
            composer.save(out)
            return Result(out,'merged.docx','Word merge keeps the first file’s headers and footers. Styles and sections from later files may shift.')
        out = work/'combined.pdf'
        with pdf.open() as combined:
            for path in paths:
                with open_pdf(path,password) as source:
                    if combined.page_count + len(source) > MAX_PAGES:
                        raise Problem(f'Merged PDFs are limited to {MAX_PAGES} pages.',413)
                    combined.insert_pdf(source,links=False,widgets=False)
            output_pdf(combined,out)
        return Result(out,'merged.pdf','Page dimensions and orientations are retained. Form fields, links, and document-level bookmarks are not copied.')
    if action == 'compress' and ext in OFFICE:
        level = data.get('level','medium')
        if level not in {'low','medium','high'}:
            raise Problem('Choose a valid compression level.')
        output = work/('compressed'+ext)
        compression = {'low':3, 'medium':6, 'high':9}[level]
        with ZipFile(first) as before, ZipFile(output,'w',ZIP_DEFLATED,compresslevel=compression) as after:
            for entry in before.infolist():
                after.writestr(entry.filename,before.read(entry),compress_type=ZIP_DEFLATED,compresslevel=compression)
        original = first.stat().st_size
        smaller = output.stat().st_size < original
        notice = 'Office package recompressed losslessly; images and formatting are unchanged.'
        if not smaller:
            notice = 'The Office package is already optimized; the original bytes are returned.'
        return Result(output if smaller else first,'compressed'+ext,notice,original)
    if action in {'split','edit','compress','preview'}:
        allowed = {'.pdf','.docx'} if action=='split' else ({'.pdf'} if action in {'edit','compress'} else {ext})
        if ext not in allowed:
            raise Problem({'edit':'This tool accepts PDF files only.', 'compress':'Choose PDF, DOCX, XLSX, or PPTX.', 'split':'Choose a PDF or DOCX file.'}[action])
        source = as_pdf(first,work,password)
        with open_pdf(source,password) as doc:
            if action == 'preview':
                selection = page_numbers(data.get('page','1'),len(doc))
                if len(selection) != 1:
                    raise Problem('Select one page to preview.')
                p = selection[0]; out = work/'preview.png'
                pixmap(doc[p],110,2_000_000).save(out)
                return Result(out,'preview.png',page_count=len(doc))
            if action == 'split':
                selection = page_numbers(data.get('pages',''),len(doc))
                out = work/'extracted.pdf'
                with pdf.open() as selected:
                    for p in selection:
                        selected.insert_pdf(doc,from_page=p,to_page=p, links=False, widgets=False)
                    output_pdf(selected,out)
                notice = 'Word page numbers follow the LibreOffice-rendered layout; the extracted result is PDF.' if ext=='.docx' else 'The original is unchanged. Form fields and links are not copied.'
                return Result(out,'extracted.pdf',notice)
            if action == 'edit':
                selection = page_numbers(data.get('pages',''),len(doc),repeats=True) if data.get('pages','').strip() else list(range(len(doc)))
                rotation = data.get('rotation','0')
                if rotation not in {'0','90','180','270'}:
                    raise Problem('Choose a valid rotation.')
                stamp = data.get('stamp','').strip()
                if len(stamp) > 80 or any(not 32 <= ord(c) <= 126 for c in stamp):
                    raise Problem('Use up to 80 printable English/ASCII characters for the stamp.')
                out = work/'edited.pdf'
                with pdf.open() as edited:
                    for p in selection:
                        edited.insert_pdf(doc,from_page=p,to_page=p,links=False,widgets=False)
                    for p in edited:
                        p.set_rotation((p.rotation+int(rotation))%360)
                        if stamp:
                            merged = pdf.Rect(12, p.rect.height-29, p.rect.width-12, p.rect.height-8)
                            if merged.is_empty:
                                raise Problem('A page is too small for a text stamp.')
                            size = min(10, merged.width/max(1,pdf.get_text_length(stamp,fontsize=1)))
                            if size < 4:
                                raise Problem('The stamp is too long to fit on one of the pages.')
                            # Stamp a rotation-aware overlay in display coordinates.
                            with pdf.open() as overlay:
                                surface = overlay.new_page(width=p.rect.width,height=p.rect.height)
                                surface.draw_rect(merged,fill=(1,1,1),color=None,fill_opacity=.87)
                                surface.insert_text((merged.x0+2,merged.y0+size+2),stamp,fontsize=size,color=(.14,.18,.15))
                                rect = p.rect * p.derotation_matrix
                                p.show_pdf_page(rect,overlay,0,rotate=p.rotation)
                    output_pdf(edited,out)
                return Result(out,'edited.pdf','Page order, rotations, and stamps are saved in a new PDF. This does not edit existing text or redact content.')
            level = data.get('level','medium')
            if level not in {'low','medium','high'}:
                raise Problem('Choose a valid compression level.')
            output = work/'compressed.pdf'
            original = first.stat().st_size
            protected = doc.needs_pass
            # Low is structural optimization; aggressive modes recompress embedded images.
            if level != 'low':
                dpi, quality = (150,75) if level=='medium' else (96,55)
                doc.rewrite_images(dpi_threshold=dpi+10,dpi_target=dpi,quality=quality,lossy=True,lossless=True,bitonal=False)
            output_pdf(doc,output)
            if not protected and output.stat().st_size >= original:
                return Result(first,'compressed.pdf','The optimizer could not make this PDF smaller; the original bytes are returned.', original)
            notice = 'Embedded images may have lower detail; text remains selectable where it was selectable before.' if level!='low' else 'Lossless structural optimization; no intentional image quality reduction.'
            if protected:
                notice += ' Output is unlocked; it may be larger than the original.'
            return Result(output,'compressed.pdf',notice,original)
    raise Problem('Unknown document tool.',404)