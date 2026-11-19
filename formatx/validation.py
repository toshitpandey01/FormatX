from pathlib import Path
from zipfile import ZipFile, BadZipFile
import re
import warnings

from defusedxml.ElementTree import fromstring
from defusedxml.common import DefusedXmlException
from xml.etree.ElementTree import ParseError
from PIL import Image
import pymupdf as pdf
from werkzeug.utils import secure_filename

MAX_PAGES = 300
FORMATS = {'.pdf', '.docx', '.xlsx', '.pptx', '.jpg', '.jpeg', '.png', '.txt', '.html', '.htm'}
OFFICE = {'.docx': 'word/document.xml', '.xlsx': 'xl/workbook.xml', '.pptx': 'ppt/presentation.xml'}
IMAGE = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG'}

class Problem(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status

def open_pdf(path, password=''):
    try:
        doc = pdf.open(path)
    except (RuntimeError, ValueError) as exc:
        raise Problem('This PDF is damaged or could not be read.') from exc
    if not doc.is_pdf or not doc.page_count or doc.is_repaired:
        doc.close()
        raise Problem('This PDF is damaged or has no pages.')
    if doc.needs_pass and not doc.authenticate(password):
        doc.close()
        raise Problem('This PDF is locked. Enter the correct PDF password and try again.')
    if doc.page_count > MAX_PAGES:
        doc.close()
        raise Problem(f'PDFs must contain {MAX_PAGES} pages or fewer.', 413)
    return doc

def check_office(path, ext):
    try:
        with ZipFile(path) as z:
            infos = z.infolist()
            names = {x.filename for x in infos}
            if len(infos) > 2500 or sum(x.file_size for x in infos) > 120 * 1024**2:
                raise Problem('The expanded Office document is too large.', 413)
            if len(names) != len(infos) or not {'[Content_Types].xml', OFFICE[ext]} <= names:
                raise Problem('The file content does not match the selected Office format.')
            for entry in infos:
                name = entry.filename
                parts = name.lower().split('/')
                if ('..' in parts or name.startswith('/') or '\\' in name or entry.flag_bits & 1):
                    raise Problem('The Office document contains unsupported archive entries.')
                if any(p in {'activex', 'embeddings'} or p.startswith('vbaproject') for p in parts):
                    raise Problem('Office files with macros, ActiveX, or embedded attachments are not supported.')
                if name.lower().endswith(('.xml', '.rels')):
                    root = fromstring(z.read(entry))
                    if name.lower().endswith('.rels'):
                        for rel in root:
                            if rel.get('TargetMode','').lower() == 'external' and not rel.get('Type','').endswith('/hyperlink'):
                                raise Problem('Remove externally linked Office resources before uploading.')
            if z.testzip():
                raise Problem('The Office file is damaged.')
    except (BadZipFile, DefusedXmlException, ParseError, RuntimeError, NotImplementedError) as exc:
        raise Problem('This Office file is damaged, encrypted, or unsupported.') from exc

def validate(path):
    ext = path.suffix
    if not path.stat().st_size:
        raise Problem('An uploaded file is empty.')
    if ext == '.pdf':
        with path.open('rb') as f:
            if b'%PDF-' not in f.read(1024):
                raise Problem('The file content does not match the PDF format.')
    elif ext in OFFICE:
        check_office(path, ext)
    elif ext in IMAGE:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(path) as im:
                    if im.format != IMAGE[ext]:
                        raise Problem('The file content does not match its image extension.')
                    if im.width * im.height > 25_000_000:
                        raise Problem('Images may contain at most 25 megapixels.', 413)
                    if getattr(im, 'n_frames', 1) != 1:
                        raise Problem('Animated images are not supported.')
                    im.verify()
        except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise Problem('This image is damaged, too large, or unsupported.') from exc
    elif ext in {'.txt','.html','.htm'}:
        if path.stat().st_size > 1024**2:
            raise Problem('Text and HTML files are limited to 1 MiB.', 413)
        try:
            content = path.read_text(encoding='utf-8-sig')
        except UnicodeError as exc:
            raise Problem('Save text and HTML files as UTF-8 before uploading.') from exc
        if any(ord(c) < 32 and c not in '\t\n\r\f' for c in content):
            raise Problem('This file contains binary data rather than plain text or HTML.')

def save_inputs(items, work, max_file):
    paths = []
    if not 1 <= len(items) <= 12:
        raise Problem('Upload between 1 and 12 files.')
    for i, file in enumerate(items):
        raw = (file.filename or '').replace('\\', '/').split('/')[-1]
        ext = Path(raw).suffix.lower()
        if ext not in FORMATS:
            raise Problem('Unsupported file type. Use PDF, DOCX, XLSX, PPTX, JPG, PNG, TXT, or HTML.')
        path = work / f'input-{i:02d}{ext}'
        file.save(path)
        if path.stat().st_size > max_file:
            raise Problem(f'Each file must be {max_file // 1024**2} MiB or smaller.', 413)
        validate(path)
        paths.append(path)
    base = secure_filename(Path(raw if len(items) == 1 else items[0].filename.replace('\\','/').split('/')[-1]).stem)
    return paths, (base[:70] or 'document')

def page_numbers(spec, count, *, repeats=False):
    terms = spec.strip().replace('–','-').replace('—','-').split(',')
    if len(terms) > MAX_PAGES:
        raise Problem(f'Enter at most {MAX_PAGES} page selections.')
    result, seen = [], set()
    for term in terms:
        match = re.fullmatch(r'\s*([0-9]{1,4})(?:\s*-\s*([0-9]{1,4}))?\s*', term)
        if not match:
            raise Problem('Enter page numbers or ascending ranges, for example 1, 3, 5–8.')
        a, b = int(match[1]), int(match[2] or match[1])
        if not 1 <= a <= b <= count:
            raise Problem(f'Page selections must be in ascending ranges between 1 and {count}.')
        for p in range(a-1, b):
            if repeats or p not in seen:
                result.append(p)
                seen.add(p)
            if len(result) > MAX_PAGES:
                raise Problem(f'Select at most {MAX_PAGES} output pages.')
    return result
