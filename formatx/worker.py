
import sys
from pathlib import Path

mode, source, output = sys.argv[1:4]
if mode == 'html':
    from weasyprint import HTML, URLFetcher

    class Offline(URLFetcher):
        def fetch(self, url, *args, **kwargs):
            # Images embedded directly in the uploaded HTML are supported; URLs and files are not.
            if url.lower().startswith(('data:image/png;', 'data:image/jpeg;')) and len(url) <= 1024**2:
                return super().fetch(url, *args, **kwargs)
            # A regular fetch error allows rendering to continue without the resource.
            raise ValueError('External assets are disabled')

    HTML(string=Path(source).read_text(encoding='utf-8-sig'), url_fetcher=Offline()).write_pdf(output)
elif mode == 'docx':
    from pdf2docx import Converter
    converter = Converter(source)
    try:
        converter.convert(output, multi_processing=False)
    finally:
        converter.close()
else:
    raise SystemExit('Unknown worker')
