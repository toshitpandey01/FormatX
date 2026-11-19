"use strict";
const $ = id => document.getElementById(id);
const dialog = $('workspace'), form = $('work-form'), input = $('upload');
const fileLimit = Number(document.body.dataset.fileMib), totalLimit = Number(document.body.dataset.requestMib);
const formats = {
  '.pdf': ['PDF', ['docx','xlsx','png','jpg']], '.docx':['Word (DOCX)',['pdf','txt']],
  '.xlsx':['Excel (XLSX)',['pdf']], '.pptx':['PowerPoint (PPTX)',['pdf']],
  '.jpg,.jpeg':['JPG image',['pdf']], '.png':['PNG image',['pdf']],
  '.txt':['Plain text (TXT)',['pdf']], '.html,.htm':['HTML',['pdf']]
};
const names = {docx:'Word (DOCX)',pdf:'PDF',xlsx:'Excel (XLSX)',png:'PNG images',jpg:'JPG images',txt:'Plain text (TXT)'};
const all = Object.keys(formats).join(',');
const tools = {
  'converter': ['convert',null,'Convert file'], 'pdf-word':['convert','.pdf','Convert to Word','docx'],
  'word-pdf':['convert','.docx','Convert to PDF','pdf'], 'merge':['merge','.pdf,.docx','Merge documents'],
  'split':['split','.pdf,.docx','Extract pages'], 'compress':['compress','.pdf,.docx,.xlsx,.pptx','Compress file'],
  'images':['images','.jpg,.jpeg,.png','Create PDF'], 'pdf-images':['convert','.pdf','Export images'],
  'edit':['edit','.pdf','Apply edits'], 'preview':['preview',all,'Preview document']
};
let current, files=[], active=null, resultURL='', previewURL='', previewIndex=-1, page=1, count=0;
function element(tag, text, cls){ const node=document.createElement(tag); if(text)node.textContent=text; if(cls)node.className=cls; return node; }
function select(key, label, entries){
  const el=element('select'); el.name=key; el.id='field-'+key;
  for(const [value,text] of entries){const opt=element('option',text);opt.value=value;el.append(opt);}
  return field(label,el);
}
function field(label,inputEl){ const el=element('label',label,'field');el.append(inputEl);return el; }
function textField(key,label,placeholder='', type='text',required=false){
  const el=element('input'); el.id='field-'+key;el.name=key;el.type=type;el.placeholder=placeholder;el.required=required;el.maxLength=key==='pages'?1700:key==='stamp'?80:250;
  if(type==='password')el.autocomplete='off'; return field(label,el);
}
function optionsLayout(where){const el=element('div','','fields');$(where).append(el);return el;}
function note(where,text){$(where).append(element('p',text,'tool-note'));}
function status(text='', error=false){$('status').textContent=text;$('status').classList.toggle('error',error);}
function clearPreview(){ if(previewURL)URL.revokeObjectURL(previewURL);previewURL='';previewIndex=-1;page=1;count=0;$('preview').hidden=true;$('preview-img').removeAttribute('src'); }
function clearResult(){ if(resultURL)URL.revokeObjectURL(resultURL);resultURL='';$('download').hidden=true;$('download').removeAttribute('href'); }
function clear(){clearResult();clearPreview();status();}
function selectedFormat(){return current==='converter'?$('field-source').value:tools[current][1];}
function accepts(){return selectedFormat().split(',');}
function multi(){return ['merge','images'].includes(current);}
function size(value){if(value<1024)return `${value} B`;if(value<1024**2)return `${(value/1024).toFixed(1)} KiB`;return `${(value/1024**2).toFixed(1)} MiB`;}
function configureOptions(){
  const box=$('options');box.replaceChildren();
  const [action,, ,fixed]=tools[current]; let target=fixed||$('field-target')?.value;
  const fields=optionsLayout('options');
  if(accepts().includes('.pdf'))fields.append(textField('password','PDF password (if locked)','','password'));
  if(action==='split')fields.append(textField('pages','Pages to extract','1, 3, 5–8','text',true));
  if(action==='edit')fields.append(textField('pages','Page order (optional)','3, 1–2, 3'),select('rotation','Rotate each page clockwise',[['0','No rotation'],['90','90°'],['180','180°'],['270','270°']]),textField('stamp','Footer stamp (optional)','Up to 80 ASCII characters'));
  if(action==='compress'){
    fields.append(select('level','Compression level',[['low','Low · lossless'],['medium','Medium · balanced'],['high','High · smaller images']]));$('field-level').value='medium';
    note('options','Medium and high may reduce PDF image quality. Office compression is lossless at every level.');
  }
  if(target==='png'||target==='jpg')fields.append(textField('pages','Pages (optional)','All pages, or e.g. 2–5'));
  if(target==='docx'){
    const label=element('label','','checkbox'), box=element('input');box.type='checkbox';box.name='ocr';box.value='1';box.checked=true;
    label.append(box,document.createTextNode('Recognize text on scanned pages (OCR)'));$('options').append(label);
    const langs=select('lang','OCR language',[['eng','English'],['fra','French'],['deu','German'],['spa','Spanish'],['chi_sim','Chinese (Simplified)'],['chi_tra','Chinese (Traditional)'],['jpn','Japanese'],['kor','Korean']]);$('options').append(langs);
    box.addEventListener('change',()=>{langs.hidden=!box.checked;});
    note('options','PDF to Word rebuilds the layout. Review the result, especially tables and scans.');
  }
  if(target==='xlsx') note('options','Extracts ruled tables with selectable text. Scans and unruled tables aren’t supported.');
  if(action==='merge') note('options','Use one format per batch. Use the arrow buttons to set merge order.');
  if(action==='split') note('options','Word files are paginated by LibreOffice. All results download as a new PDF.');
  if(action==='edit') note('options','Omit a page to remove it, or list it twice to duplicate it. This tool does not edit existing text or redact content.');
  if(current==='converter' && ['.html,.htm'].includes(selectedFormat())) note('options','External images, stylesheets, and fonts are not fetched.');
}
function uploadHelp(){input.accept=selectedFormat();input.multiple=multi();$('file-help').textContent=`${accepts().map(x=>x.slice(1).toUpperCase()).join(', ')} · ${fileLimit} MiB per file${multi()?` · up to 12 files / ${totalLimit} MiB per request`:''}`;}
function targets(){
  const target=$('field-target');target.replaceChildren();
  for(const value of formats[selectedFormat()][1]) {const opt=element('option',names[value]);opt.value=value;target.append(opt);}
}
function launch(button){
  current=button.dataset.tool;files=[];clear();input.value='';$('settings').replaceChildren();
  $('work-title').textContent=button.querySelector('.card-title').textContent;$('work-desc').textContent=button.querySelector('.card-desc').textContent;
  if(current==='converter'){
    const fields=optionsLayout('settings');fields.append(select('source','Convert from',Object.entries(formats).map(([key,[label]])=>[key,label])),select('target','Convert to',[]));targets();
    $('field-source').addEventListener('change',()=>{targets();files=[];clear();uploadHelp();configureOptions();drawFiles();});
    $('field-target').addEventListener('change',()=>{clear();configureOptions();});
  }else if(current==='pdf-images')optionsLayout('settings').append(select('target','Image format',[['png','PNG'],['jpg','JPG']]));
  configureOptions();uploadHelp();drawFiles();$('run').textContent=tools[current][2];dialog.showModal();
}
function drawFiles(){
  $('file-list').replaceChildren();
  files.forEach((file,i)=>{
    const li=element('li');li.append(element('span',`${file.name} · ${size(file.size)}`,'file-name'));
    function add(label,symbol,handler,disabled=false){const btn=element('button',symbol);btn.type='button';btn.disabled=disabled||!!active;btn.setAttribute('aria-label',`${label} ${file.name}`);btn.title=label;btn.addEventListener('click',handler);li.append(btn);}
    if(current!=='preview')add('Preview','◎',()=>send(i,1));
    if(multi()){
      const move=(direction)=>{const j=i+direction;[files[i],files[j]]=[files[j],files[i]];clear();drawFiles();const row=$('file-list').children[j];const controls=[...row.querySelectorAll('button')];(controls[direction===-1?1:2].disabled?controls[0]:controls[direction===-1?1:2]).focus();};
      add('Move up','↑',()=>move(-1),i===0);add('Move down','↓',()=>move(1),i===files.length-1);
    }
    add('Remove','×',()=>{files.splice(i,1);clear();drawFiles();input.focus();});$('file-list').append(li);
  });
}
function addFiles(incoming){
  if(active)return;clear();const rejected=[];let temp=multi()?[...files]:[];
  for(const file of incoming){
    const extension='.'+file.name.split('.').pop().toLowerCase();
    if(!accepts().includes(extension)){rejected.push(`${file.name}: unsupported file type.`);continue;}
    if(!file.size||file.size>fileLimit*1024**2){rejected.push(`${file.name}: empty or larger than ${fileLimit} MiB.`);continue;}
    if(temp.length>=(multi()?12:1)){rejected.push(multi()?'Choose at most 12 files.':'This tool takes one file.');break;}
    if(temp.reduce((sum,f)=>sum+f.size,0)+file.size>=totalLimit*1024**2){rejected.push(`The batch must be below ${totalLimit} MiB.`);break;}
    temp.push(file);
  }
  if(temp.length||multi())files=temp;
  drawFiles(); if(rejected.length)status(rejected.join('\n'),true);
}
function busy(waiting){
  for(const el of form.querySelectorAll('input,select'))el.disabled=waiting;
  $('run').disabled=waiting;$('cancel').hidden=!waiting;$('progress').hidden=!waiting;
  $('prev').disabled=waiting||page<=1;$('next').disabled=waiting||page>=count;drawFiles();
}
function send(showIndex=null, which=1){
  if(active)return;
  const [action,, ,fixed]=tools[current];
  const isPreview=showIndex!==null||action==='preview';
  if(!files.length){status('Choose a file before continuing.',true);input.focus();return;}
  if(!isPreview && action==='merge' && files.length<2){status('Choose at least two documents to merge.',true);return;}
  if(!isPreview && !form.reportValidity())return;
  const data=new FormData(form);if(fixed)data.set('target',fixed);
  if(isPreview){data.set('page',String(which));data.append('files',files[showIndex??0]);}
  else{clear();files.forEach(file=>data.append('files',file));}
  const endpoint=isPreview?'preview':action;
  const xhr=new XMLHttpRequest();active=xhr;xhr.open('POST','/api/'+endpoint);xhr.setRequestHeader('X-FormatX','1');xhr.responseType='blob';xhr.timeout=15*60*1000;
  $('progress').value=0;busy(true);status('Uploading…');
  xhr.upload.addEventListener('progress',e=>{if(active===xhr&&e.lengthComputable){$('progress').max=e.total;$('progress').value=e.loaded;}});
  xhr.upload.addEventListener('load',()=>{if(active===xhr){$('progress').removeAttribute('value');status('Processing document…');}});
  function finish(){if(active!==xhr)return false;active=null;busy(false);return true;}
  xhr.addEventListener('load',async()=>{
    if(!finish())return;
    if(xhr.status<200||xhr.status>=300){let error='The request could not be completed.';try{error=JSON.parse(await xhr.response.text()).error||error;}catch{} if(dialog.open&&!active)status(error,true);return;}
    const url=URL.createObjectURL(xhr.response);
    if(isPreview){clearPreview();previewURL=url;previewIndex=showIndex??0;page=which;count=Number(xhr.getResponseHeader('X-FormatX-Pages'));
      $('preview-img').src=url;$('preview-img').alt=`Page ${page} of ${files[previewIndex].name}`;
      $('page-label').textContent=`Page ${page} of ${count}`;$('preview').hidden=false;$('prev').disabled=page<=1;$('next').disabled=page>=count;status(`Preview: ${files[previewIndex].name}`);
    }else{
      resultURL=url;const link=$('download');link.href=url;link.download=xhr.getResponseHeader('X-FormatX-Name')||'formatx-result';link.hidden=false;
      const original=Number(xhr.getResponseHeader('X-FormatX-Original-Bytes'));let summary=`Ready to download · ${size(xhr.response.size)}`;
      if(original){const reduction=100*(1-xhr.response.size/original);summary=`${size(original)} → ${size(xhr.response.size)} · ${reduction>=0?`${reduction.toFixed(1)}% smaller`:`${(-reduction).toFixed(1)}% larger`}`;}
      const notice=xhr.getResponseHeader('X-FormatX-Notice');status(summary+(notice?'\n'+decodeURIComponent(notice):''));
    }
  });
  xhr.addEventListener('error',()=>{if(finish())status('Connection lost. Check that FormatX is running and retry.',true);});
  xhr.addEventListener('timeout',()=>{if(finish())status('This request timed out. Try a smaller document.',true);});
  xhr.addEventListener('abort',()=>{if(finish())status('Request canceled in the browser. Server-side processing may finish before cleanup.');});
  xhr.send(data);
}
document.querySelectorAll('[data-tool]').forEach(btn=>btn.addEventListener('click',()=>launch(btn)));
input.addEventListener('change',()=>{addFiles(input.files);input.value='';});
$('drop').addEventListener('dragover',e=>{e.preventDefault();if(!active)$('drop').classList.add('active');});
$('drop').addEventListener('dragleave',()=> $('drop').classList.remove('active'));
$('drop').addEventListener('drop',e=>{e.preventDefault();$('drop').classList.remove('active');addFiles(e.dataTransfer.files);});
$('close').addEventListener('click',()=>dialog.close());
dialog.addEventListener('close',()=>{if(active)active.abort();files=[];input.value='';clear();$('options').replaceChildren();$('settings').replaceChildren();});
form.addEventListener('submit',e=>{e.preventDefault();send();});
$('cancel').addEventListener('click',()=>active?.abort());
$('prev').addEventListener('click',()=>{if(page>1)send(previewIndex,page-1);});
$('next').addEventListener('click',()=>{if(page<count)send(previewIndex,page+1);});
