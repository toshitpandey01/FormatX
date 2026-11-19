
from pathlib import Path
import os
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

import pymupdf as pdf
import pytest
from playwright.sync_api import sync_playwright, expect
from test_api import sample_pdf

@pytest.fixture(scope='module')
def server():
    root=Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    with subprocess.Popen([sys.executable,'-m','flask','--app','formatx','run','--no-reload','--port',str(port)],
                          cwd=root,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) as proc:
        url=f'http://127.0.0.1:{port}'
        try:
            for _ in range(100):
                try:
                    with urlopen(url+'/health', timeout=0.2) as r:
                        assert r.status==200
                    break
                except OSError:
                    time.sleep(.1)
            else:
                pytest.fail('FormatX did not start')
            yield url
        finally:
            proc.terminate()
            proc.wait(timeout=10)

@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch()
        yield browser
        browser.close()

def test_desktop_merge_reorder_preview_and_download(server,browser,tmp_path):
    page=browser.new_page(viewport={'width':1366,'height':1060},accept_downloads=True)
    errors=[];page.on('pageerror',lambda e: errors.append(str(e)))
    page.goto(server)
    screenshot=os.getenv('FORMATX_SCREENSHOT')
    if screenshot: page.screenshot(path=screenshot,full_page=True)
    expect(page.get_by_role('heading',name='A better place for your files.')).to_be_visible()
    page.get_by_role('link',name='Explore the tools').click()
    page.get_by_role('button',name='Merge Documents').click()
    page.locator('#upload').set_input_files([{'name':'a.pdf','mimeType':'application/pdf','buffer':sample_pdf('A','B')},
                                             {'name':'c.pdf','mimeType':'application/pdf','buffer':sample_pdf('C')}])
    page.get_by_role('button',name='Preview a.pdf').click()
    expect(page.get_by_text('Page 1 of 2')).to_be_visible()
    page.get_by_role('button',name='Next').click()
    expect(page.get_by_text('Page 2 of 2')).to_be_visible()
    assert page.locator('#preview-img').evaluate('(img) => img.complete && img.naturalWidth > 0')
    page.get_by_role('button',name='Move up c.pdf').click()
    page.get_by_role('button',name='Merge documents',exact=True).click()
    expect(page.get_by_text('Ready to download',exact=False)).to_be_visible()
    with page.expect_download() as d:
        page.get_by_role('link',name='Download result').click()
    result=tmp_path/'merged.pdf';d.value.save_as(result)
    with pdf.open(result) as doc: assert [p.get_text().strip() for p in doc]==['C','A','B']
    page.keyboard.press('Escape');expect(page.locator('#workspace')).not_to_be_visible()
    assert errors==[]
    page.close()

def test_mobile_converter_validation_and_drop(server,browser):
    page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
    page.goto(server)
    assert page.evaluate('document.documentElement.scrollWidth === window.innerWidth')
    page.get_by_role('button',name='Document Converter').click()
    dialog=page.get_by_role('dialog');expect(dialog).to_be_visible()
    assert dialog.bounding_box()['width']<=390
    page.get_by_label('Convert from').select_option('.txt')
    expect(page.get_by_label('Convert to')).to_have_value('pdf')
    page.get_by_role('button',name='Convert file').click();expect(page.get_by_text('Choose a file before continuing.')).to_be_visible()
    transfer=page.evaluate_handle("""() => { const packet=new DataTransfer(); packet.items.add(new File(['Mobile drag and drop'], 'note.txt', {type:'text/plain'})); return packet; }""")
    page.locator('#drop').dispatch_event('drop',{'dataTransfer':transfer})
    expect(page.get_by_text('note.txt',exact=False)).to_be_visible()
    page.get_by_role('button',name='Convert file').click();expect(page.get_by_role('link',name='Download result')).to_be_visible()
    page.get_by_role('button',name='Close workspace').click();expect(dialog).not_to_be_visible()
    page.close()
