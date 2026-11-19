from io import BytesIO
from zipfile import ZipFile, ZIP_STORED
import shutil

import pymupdf as pdf
import pytest
from docx import Document
from openpyxl import Workbook, load_workbook
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.util import Inches

from formatx import create_app
from formatx.validation import page_numbers, Problem

@pytest.fixture
def api():
    return create_app({'TESTING':True}).test_client()

def upload(api, action, docs, **options):
    return api.post('/api/'+action, data={**options,'files':[(BytesIO(data),name) for name,data in docs]},
                    headers={'X-FormatX':'1'},content_type='multipart/form-data',buffered=True)

def output(response, code=200):
    assert response.status_code == code, response.json if response.is_json else response.status_code
    return response.data

def sample_pdf(*labels, locked=False):
    with pdf.open() as doc:
        for i,label in enumerate(labels):
            p=doc.new_page(width=612 if i%2 else 595,height=400 if i%2 else 842)
            p.insert_text((45,90),label,fontsize=20)
        if locked:
            return doc.tobytes(encryption=pdf.PDF_ENCRYPT_AES_256,owner_pw='owner1',user_pw='apricot')
        return doc.tobytes()

def sample_word(text, second=None):
    doc=Document();doc.add_heading(text,0);doc.add_paragraph('Document body with café and text.');
    table=doc.add_table(rows=1,cols=2);table.rows[0].cells[0].text='Column One';table.rows[0].cells[1].text='Column Two'
    doc.add_picture(BytesIO(image('PNG',150,90)))
    if second:
        doc.add_page_break();doc.add_heading(second,0)
    buf=BytesIO();doc.save(buf);return buf.getvalue()

def image(fmt,w=320,h=200):
    buf=BytesIO();Image.new('RGB',(w,h),(80,121,167)).save(buf,format=fmt);return buf.getvalue()

def pages(data):
    with pdf.open(stream=data,filetype='pdf') as doc:
        return [p.get_text().strip() for p in doc]

def test_routes(api):
    assert api.get('/health').json=={'status':'ok'}
    home=api.get('/');assert home.status_code==200
    assert home.data.count(b'data-tool=')==10
    assert api.post('/api/merge').status_code==403
    assert upload(api,'unknown',[('a.pdf',b'1')]).status_code==404

@pytest.mark.parametrize('spec,expected',[('1',[0]),('2–4, 1, 4',[1,2,3,0]),('5—6',[4,5])])
def test_ranges(spec,expected):
    assert page_numbers(spec,7)==expected

@pytest.mark.parametrize('spec',['','0','4-2','a','1,,2','7–8','00000'])
def test_bad_ranges(spec):
    with pytest.raises(Problem): page_numbers(spec,7)

def test_split_order_inclusive_and_original(api):
    data=sample_pdf(*[f'Test Page {i}' for i in range(1,51)])
    docs=[('Résumé.pdf',data)]
    selected=upload(api,'split',docs,pages='5–15')
    assert pages(output(selected))==[f'Test Page {i}' for i in range(5,16)]
    assert len(pages(data))==50
    assert pages(output(upload(api,'split',docs,pages='3, 1, 2–3')))==['Test Page 3','Test Page 1','Test Page 2']
    assert upload(api,'split',docs,pages='49–52').status_code==400

def test_merge_duplicate_names_dimensions_and_order(api):
    docs=[('same.pdf',sample_pdf('First','Wide')),('same.pdf',sample_pdf('Last'))]
    result=output(upload(api,'merge',docs));assert pages(result)==['First','Wide','Last']
    with pdf.open(stream=result,filetype='pdf') as doc:
        assert doc[1].rect.width==612 and doc[1].rect.height==400
    assert upload(api,'merge',docs[:1]).status_code==400
    assert upload(api,'merge',[docs[0],('word.docx',sample_word('Word'))]).status_code==400

def test_merge_word(api):
    result=Document(BytesIO(output(upload(api,'merge',[('word.docx',sample_word('Garden')),('word.docx',sample_word('Workshop'))]))))
    assert [p.text for p in result.paragraphs if p.text in {'Garden','Workshop'}]==['Garden','Workshop']
    assert len(result.tables)==2 and len(result.inline_shapes)==2

@pytest.mark.skipif(not shutil.which('libreoffice'),reason='LibreOffice not installed')
def test_office_rendering_and_word_split(api):
    word=sample_word('Intro to FormatX','Chapter Two');doc=[('work.docx',word)]
    types=pages(output(upload(api,'convert',doc,target='pdf')));assert len(types)==2 and 'Chapter Two' in types[1] and 'Column One' in types[0]
    extracted=output(upload(api,'split',doc,pages='2'));assert pages(extracted)==['Chapter Two']
    book=Workbook();book.active.append(['Items','Price']);book.active.append(['Paper',7]); b=BytesIO();book.save(b)
    assert 'Paper' in ' '.join(pages(output(upload(api,'convert',[('ledger.xlsx',b.getvalue())],target='pdf'))))
    deck=Presentation();slide=deck.slides.add_slide(deck.slide_layouts[6]);slide.shapes.add_textbox(Inches(1),Inches(1),Inches(4),Inches(1)).text='Quarterly briefing';b=BytesIO();deck.save(b)
    assert 'Quarterly briefing' in ' '.join(pages(output(upload(api,'convert',[('brief.pptx',b.getvalue())],target='pdf'))))

@pytest.mark.skipif(not shutil.which('java'),reason='Java JDK not installed')
def test_java_text_extraction(api):
    out=output(upload(api,'convert',[('sample.docx',sample_word('Workshop'))],target='txt')).decode('utf-8')
    assert 'Workshop' in out and 'café' in out and 'Column Two' in out

def test_txt_and_html_to_pdf(api):
    assert 'Café' in pages(output(upload(api,'convert',[('letter.txt','Café & <Notes>'.encode())],target='pdf')))[0]
    html=b'<!doctype html><style>@page{size:A5} b{color:red}</style><b>Printable HTML</b><img src="file:///does-not-exist.png">'
    result=output(upload(api,'convert',[('web.html',html)],target='pdf'))
    assert pages(result)==['Printable HTML']
    with pdf.open(stream=result,filetype='pdf') as doc:
        assert doc[0].rect.width==pytest.approx(419.5,abs=1)

def test_pdf_to_docx(api):
    result=output(upload(api,'convert',[('chapter.pdf',sample_pdf('Editable heading','Second page'))],target='docx'))
    text=' '.join(p.text for p in Document(BytesIO(result)).paragraphs)
    assert 'Editable heading' in text and 'Second page' in text

def decorated_cover():
    """A bordered cover with mirrored corner ornaments and a logo, like a Word art-border title page."""
    orn=Image.new('RGB',(120,120),'white');ImageDraw.Draw(orn).polygon([(2,2),(115,2),(2,115)],fill='black');ob=BytesIO();orn.save(ob,format='PNG')
    logo=Image.new('RGB',(100,100),'white');ImageDraw.Draw(logo).ellipse((5,5,95,95),fill=(30,60,160));lb=BytesIO();logo.save(lb,format='PNG')
    with pdf.open() as doc:
        p=doc.new_page(width=595,height=842);p.draw_rect(pdf.Rect(30,30,565,812),width=5)
        for x,y,turn in [(22,22,0),(503,22,90),(503,750,180),(22,750,270)]:
            p.insert_image(pdf.Rect(x,y,x+70,y+70),stream=ob.getvalue(),rotate=turn)
        p.insert_image(pdf.Rect(247,430,347,530),stream=lb.getvalue())
        p.insert_textbox(pdf.Rect(60,110,535,160),'Project Report',fontsize=14,align=1)
        p=doc.new_page(width=595,height=842);p.insert_text((60,100),'Plain second page',fontsize=12)
        return doc.tobytes()

def test_pdf_to_docx_keeps_page_art(api):
    response=upload(api,'convert',[('cover.pdf',decorated_cover())],target='docx')
    result=Document(BytesIO(output(response)))
    assert 'Project Report' in ' '.join(p.text for p in result.paragraphs)
    first,second=result.sections[0],result.sections[1]
    assert 'behindDoc="1"' in first.header._element.xml and 'a:blip' in first.header._element.xml
    assert 'a:blip' not in second.header._element.xml and not second.header.is_linked_to_previous
    assert 'page background' in response.headers['X-FormatX-Notice'] or 'page%20background' in response.headers['X-FormatX-Notice']

def filled_frame_cover():
    """Like a Word export: border made of filled black shapes, unflipped corner images, a logo."""
    orn=Image.new('RGB',(120,120),'white');ImageDraw.Draw(orn).polygon([(2,2),(115,2),(2,115)],fill='black');ob=BytesIO();orn.save(ob,format='PNG')
    logo=Image.new('RGB',(100,100),'white');ImageDraw.Draw(logo).ellipse((5,5,95,95),fill=(30,60,160));lb=BytesIO();logo.save(lb,format='PNG')
    with pdf.open() as doc:
        p=doc.new_page(width=612,height=792)
        frame=p.new_shape();frame.draw_rect(pdf.Rect(17,17,595,775));frame.draw_rect(pdf.Rect(23,23,589,769))
        frame.finish(color=None,fill=(0,0,0),even_odd=True);frame.commit()  # one big filled shape with a hole
        for x,y in [(25,24),(538,25),(25,720),(539,718)]:
            p.insert_image(pdf.Rect(x,y,x+48,y+48),stream=ob.getvalue())
        p.insert_image(pdf.Rect(252,458,360,554),stream=lb.getvalue())
        p.insert_textbox(pdf.Rect(60,110,550,160),'Filled frame cover',fontsize=14,align=1)
        return doc.tobytes()

def test_pdf_to_docx_filled_frame_art(api):
    response=upload(api,'convert',[('cover.pdf',filled_frame_cover())],target='docx')
    result=Document(BytesIO(output(response)))
    assert 'Filled frame cover' in ' '.join(p.text for p in result.paragraphs)
    assert 'behindDoc="1"' in result.sections[0].header._element.xml
    assert 'a:blip' not in result.element.body.xml

def test_floating_pictures_get_distinct_stacking_order(api, tmp_path):
    from formatx.processing import add_backdrops
    # A converted file with several floating pictures: Word hides small ones under a big opaque one
    # when they share relativeHeight, so each picture needs its own order, largest at the back.
    doc=Document();para=doc.add_paragraph('x')
    for size in (3000000,600000,1200000):
        para.add_run().add_picture(BytesIO(image('PNG',40,40)))
    ns='{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}'
    from docx.oxml import parse_xml
    for drawing,size in zip(doc.element.body.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}drawing'),(3000000,600000,1200000)):
        inline=drawing[0];anchor=parse_xml(f'<wp:anchor xmlns:wp="{ns[1:-1]}" distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="0" behindDoc="1" locked="0" layoutInCell="1" allowOverlap="1"><wp:simplePos x="0" y="0"/><wp:positionH relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionH><wp:positionV relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionV><wp:extent cx="{size}" cy="{size}"/><wp:wrapNone/><wp:docPr id="1" name="p"/><wp:cNvGraphicFramePr/></wp:anchor>')
        anchor.append(inline.graphic);drawing.remove(inline);drawing.append(anchor)
    path=tmp_path/'f.docx';doc.save(path)
    add_backdrops(path,{},1)
    anchors=list(Document(path).element.body.iter(ns+'anchor'))
    order={int(a.find(ns+'extent').get('cx')):int(a.get('relativeHeight')) for a in anchors}
    assert len(set(order.values()))==3 and order[3000000]<order[1200000]<order[600000]

@pytest.mark.skipif(not shutil.which('tesseract'),reason='Tesseract not installed')
def test_ocr_pdf_to_docx(api):
    im=Image.new('RGB',(1000,500),'white');draw=ImageDraw.Draw(im)
    try: font=ImageFont.truetype('DejaVuSans.ttf',66)
    except OSError: font=ImageFont.load_default(size=60)
    draw.text((68,130),'SCANNED INVOICE',fill='black',font=font);b=BytesIO();im.save(b,format='PNG')
    source=output(upload(api,'images',[('page.png',b.getvalue())]));assert not any(pages(source))
    response=upload(api,'convert',[('scan.pdf',source)],target='docx',ocr='1',lang='eng')
    result=Document(BytesIO(output(response)));assert 'SCANNED INVOICE' in ' '.join(p.text for p in result.paragraphs)
    assert 'OCR' in response.headers['X-FormatX-Notice']

def test_table_extraction_xlsx(api):
    with pdf.open() as doc:
        page=doc.new_page()
        for y in [100,130,160]: page.draw_line((50,y),(250,y))
        for x in [50,150,250]: page.draw_line((x,100),(x,160))
        for x,y,text in [(60,120,'Name'),(160,120,'Value'),(60,150,'Paper'),(160,150,'=1+2')]: page.insert_text((x,y),text)
        source=doc.tobytes()
    result=load_workbook(BytesIO(output(upload(api,'convert',[('table.pdf',source)],target='xlsx'))))
    assert result.active['A2'].value=='Paper' and result.active['B2'].value=='=1+2' and result.active['B2'].data_type=='s'
    assert upload(api,'convert',[('plain.pdf',sample_pdf('No tables'))],target='xlsx').status_code==422

def test_image_input_and_export(api):
    generated=output(upload(api,'images',[('vista.jpg',image('JPEG')),('portrait.png',image('PNG',100,200))]))
    with pdf.open(stream=generated,filetype='pdf') as doc:
        assert len(doc)==2 and doc[0].rect.width>doc[0].rect.height and doc[1].rect.width<doc[1].rect.height
    source=[('collection.pdf',generated)]
    bundle=output(upload(api,'convert',source,target='png',pages='2, 1'))
    with ZipFile(BytesIO(bundle)) as z:
        assert z.namelist()==['001-page-002.png','002-page-001.png']
        with Image.open(z.open(z.namelist()[0])) as im: assert im.format=='PNG' and im.height>im.width
    with Image.open(BytesIO(output(upload(api,'convert',source,target='jpg',pages='1')))) as im: assert im.format=='JPEG'

def test_preview_lock_and_page_edit(api):
    original=sample_pdf('One','Two',locked=True); docs=[('lock.pdf',original)]
    assert upload(api,'preview',docs,page='2',password='wrong').status_code==400
    response=upload(api,'preview',docs,page='2',password='apricot');assert response.headers['X-FormatX-Pages']=='2'
    assert output(response).startswith(b'\x89PNG')
    result=output(upload(api,'edit',docs,pages='2,1,2',rotation='90',stamp='REVIEW COPY',password='apricot'))
    with pdf.open(stream=result,filetype='pdf') as doc:
        assert [p.rotation for p in doc]==[90,90,90]
        assert [p.get_text().splitlines()[0] for p in doc]==['Two','One','Two']
        for p in doc:
            stamps=p.search_for('REVIEW COPY');assert len(stamps)==1
            position=stamps[0]*p.rotation_matrix
            assert position.y0>p.rect.height-38 and position.x0<35
    with pdf.open(stream=original,filetype='pdf') as doc: assert doc.needs_pass

def test_compress_real_reduction_and_levels(api):
    from random import Random
    im=Image.frombytes('RGB',(1400,1300),Random(5).randbytes(1400*1300*3));buf=BytesIO();im.save(buf,format='JPEG',quality=99)
    with pdf.open() as doc:
        p=doc.new_page();p.insert_image(pdf.Rect(20,20,540,510),stream=buf.getvalue());p.insert_text((25,560),'Selectable caption');data=doc.tobytes()
    for level in ['low','medium','high']:
        response=upload(api,'compress',[('image-heavy.pdf',data)],level=level)
        content=output(response); assert int(response.headers['X-FormatX-Original-Bytes'])==len(data)
        assert pages(content)==['Selectable caption']
        assert len(content)<=len(data)
        if level=='high': assert len(content)<len(data)*.5
    assert upload(api,'compress',[('photo.png',image('PNG'))],level='high').status_code==400

def test_office_compression_is_lossless(api):
    raw=BytesIO()
    with ZipFile(BytesIO(sample_word('Archive'))) as original, ZipFile(raw,'w',ZIP_STORED) as larger:
        for name in original.namelist(): larger.writestr(name,original.read(name))
    response=upload(api,'compress',[('archive.docx',raw.getvalue())],level='high')
    result=output(response)
    assert len(result)<len(raw.getvalue()) and int(response.headers['X-FormatX-Original-Bytes'])==len(raw.getvalue())
    assert Document(BytesIO(result)).paragraphs[0].text=='Archive'
    with ZipFile(BytesIO(result)) as a, ZipFile(raw) as b:
        assert set(a.namelist())==set(b.namelist()) and all(a.read(name)==b.read(name) for name in a.namelist())

@pytest.mark.parametrize('name,data,code',[('fake.pdf',b'not a PDF',400),('damaged.pdf',b'%PDF-1.4\nEND',400),('empty.txt',b'',400),('image.png',image('JPEG'),400),('bad.docx',b'not a ZIP',400),('bad.html',b'\x00binary',400),('tool.exe',b'not allowed',400)])
def test_upload_errors(api,name,data,code):
    response=upload(api,'preview',[(name,data)]);assert response.status_code==code and response.json['error']

def test_upload_limits_and_sanitized_name():
    client=create_app({'TESTING':True,'MAX_FILE_BYTES':100,'MAX_CONTENT_LENGTH':4096}).test_client()
    assert upload(client,'convert',[('big.txt',b'1'*300)],target='pdf').status_code==413
    assert upload(client,'convert',[('big.txt',b'1'*5000)],target='pdf').status_code==413
    client=create_app({'TESTING':True}).test_client()
    result=upload(client,'split',[('../../Pâge.pdf',sample_pdf('One'))],pages='1')
    assert output(result).startswith(b'%PDF-') and result.headers['X-FormatX-Name']=='Page-extracted.pdf'