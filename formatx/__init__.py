import os
from pathlib import Path
import shutil
import tempfile
from threading import BoundedSemaphore

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException

from .processing import process
from .validation import Problem, save_inputs

TOOLS = [
    ('converter','Document Converter','Convert Office files, PDFs, web pages and plain text.','⇄','blue'),
    ('pdf-word','PDF to Word','Rebuild editable Word documents, with OCR for scans.','W','tan'),
    ('word-pdf','Word to PDF','Export a share-ready version of your Word document.','↗','olive'),
    ('merge','Merge Documents','Arrange and combine multiple PDFs or Word files.','⊞','cream'),
    ('split','Split & Extract','Pull out individual pages or a custom page range.','✂','peach'),
    ('compress','PDF & Office Compressor','Reduce PDF size or optimize Office files losslessly.','↘','blue'),
    ('images','Images to PDF','Combine JPG and PNG images into a single PDF.','▧','olive'),
    ('pdf-images','PDF to Images','Render selected pages as PNG or JPG files.','▤','tan'),
    ('edit','Edit PDF','Reorder, rotate, remove, duplicate, or stamp pages.','✎','peach'),
    ('preview','Document Preview','Inspect individual pages before you process a file.','◎','cream'),
]


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(MAX_CONTENT_LENGTH=int(os.getenv('FORMATX_REQUEST_MIB','60'))*1024**2,
                            MAX_FILE_BYTES=int(os.getenv('FORMATX_FILE_MIB','40'))*1024**2,
                            MAX_FORM_MEMORY_SIZE=256*1024, MAX_FORM_PARTS=30)
    if config:
        app.config.update(config)
    # PyMuPDF is not thread-safe; use multiple single-threaded workers for concurrency.
    slot = BoundedSemaphore(1)

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        return response

    @app.errorhandler(Problem)
    def problem(exc):
        return jsonify(error=str(exc)),exc.status

    @app.errorhandler(413)
    def too_large(exc):
        return jsonify(error='The upload exceeds the request or form limits. Try smaller or fewer files.'),413

    @app.get('/')
    def index():
        return render_template('index.html', tools=TOOLS, file_mib=app.config['MAX_FILE_BYTES']//1024**2,
                               request_mib=app.config['MAX_CONTENT_LENGTH']//1024**2)

    @app.get('/health')
    def health():
        return jsonify(status='ok')

    @app.post('/api/<action>')
    def operation(action):
        if action not in {'convert','merge','split','edit','compress','images','preview'}:
            raise Problem('Unknown document tool.',404)
        if request.headers.get('X-FormatX') != '1':
            raise Problem('Expected the X-FormatX: 1 request header.',403)
        if request.mimetype != 'multipart/form-data':
            raise Problem('Send the document as multipart form data.',415)
        if not slot.acquire(blocking=False):
            raise Problem('All processing slots are busy. Please retry shortly.',503)
        spool = None
        try:
            with tempfile.TemporaryDirectory(prefix='formatx-') as folder:
                work = Path(folder).resolve()
                paths, base = save_inputs(request.files.getlist('files'),work,app.config['MAX_FILE_BYTES'])
                result = process(action,paths,request.form,work)
                if not result.path.is_file():
                    raise Problem('No output was produced by the processing engine.',422)
                size = result.path.stat().st_size
                if size > 120 * 1024**2:
                    raise Problem('The result exceeds 120 MiB. Try a smaller batch.',413)
                spool = tempfile.SpooledTemporaryFile(max_size=4*1024**2, mode='w+b')
                with result.path.open('rb') as source:
                    shutil.copyfileobj(source,spool)
                spool.seek(0)
            name = f'{base}-{result.suffix}'
            response = send_file(spool, download_name=name, as_attachment=action!='preview', conditional=False)
            response.content_length = size
            response.headers['X-FormatX-Name'] = name
            if result.notice:
                from urllib.parse import quote
                response.headers['X-FormatX-Notice'] = quote(result.notice,safe='')
            if result.original_size:
                response.headers['X-FormatX-Original-Bytes'] = str(result.original_size)
            if result.page_count:
                response.headers['X-FormatX-Pages'] = str(result.page_count)
            return response
        except (Problem, HTTPException):
            if spool: spool.close()
            raise
        except Exception as exc:
            if spool: spool.close()
            app.logger.warning('Document operation %s failed (%s)',action,type(exc).__name__)
            raise Problem('The document could not be processed. Verify that it opens normally, or try a smaller file.',422) from exc
        finally:
            slot.release()
    return app
