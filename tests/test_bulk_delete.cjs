// Isolated DOM behavior tests. Never calls the running server or user database.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('../.runtime/ui-test/node_modules/jsdom');
const root = path.resolve(__dirname, '..');
async function waitFor(fn) {
  for (let i=0;i<150;i++) {
    if (fn()) return;
    await new Promise(resolve=>setTimeout(resolve,10));
  }
  throw new Error('Bulk-delete DOM update timed out');
}
async function main() {
  const dom = new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{url:'http://localhost:8000',runScripts:'outside-only'});
  const w=dom.window, d=w.document;
  w.scrollTo=()=>{};
  const row={category:'요리',time:5,ingredients:['달걀'],steps:['익혀요.'],semantic:{spice_level:null},index_status:'indexed'};
  let saved=[{...row,id:'a',title:'<img src=x> 첫 요리'},{...row,id:'b',title:'두 번째 요리'},{...row,id:'c',title:'남길 요리'}];
  let confirmed=false,holdNextList=false,releaseList;
  const failures=new Set(['b']), deleted=[], confirmations=[];
  w.confirm=message=>{confirmations.push(message);return confirmed;};
  w.fetch=async(url,opts={})=>{
    let out;
    if(url==='/api/recipes') {
      const snapshot=[...saved];
      if(holdNextList) { holdNextList=false; await new Promise(resolve=>{releaseList=resolve;}); }
      out={recipes:snapshot};
    }
    else if(url.startsWith('/api/recipes/')&&opts.method==='DELETE') {
      const id=decodeURIComponent(url.split('/').pop());
      deleted.push(id);
      if(failures.has(id)) return{ok:false,status:422,text:async()=>JSON.stringify({error:'검색 저장소 연결 실패'})};
      saved=saved.filter(r=>r.id!==id);out={id,deleted:true};
    } else if(url==='/api/pantry') out={pantry:[]};
    else if(url==='/api/status') out={running:true,modelInstalled:true,model:'fixture'};
    else if(url==='/api/health') out={sqlite:{ready:true},ollama:{ready:true},embedding:{ready:true},qdrant:{ready:true,needsReindex:0}};
    else throw new Error('Unexpected request: '+url);
    return{ok:true,status:200,text:async()=>JSON.stringify(out)};
  };
  try {
    w.eval(fs.readFileSync(path.join(root,'app.js'),'utf8'));
    await waitFor(()=>d.querySelectorAll('.recipe-card').length===3);
    const toggle=d.querySelector('#toggle-selection');
    assert.ok(toggle,'recipe list must offer selection mode');
    toggle.click();
    assert.equal(toggle.getAttribute('aria-pressed'),'true');
    assert.equal(d.querySelectorAll('.recipe-card[role="button"]').length,0,'checkboxes must not be nested inside button roles');
    assert.equal(d.querySelectorAll('.recipe-select').length,3);
    assert.equal(d.querySelector('#delete-selected').disabled,true);
    assert.equal(d.querySelector('#recipe-grid img'),null,'selection labels must escape recipe titles');
    d.querySelector('#select-all-recipes').click();
    assert.equal(d.querySelectorAll('.recipe-select:checked').length,3);
    d.querySelector('#clear-recipe-selection').click();
    assert.equal(d.querySelectorAll('.recipe-select:checked').length,0);
    d.querySelector('[data-select-id="a"]').click();
    d.querySelector('[data-select-id="b"]').click();
    assert.equal(d.querySelector('#home-view').classList.contains('active'),true,'selecting must not open detail');
    d.querySelector('#delete-selected').click();
    assert.equal(deleted.length,0,'cancel must send no delete requests');
    assert.ok(confirmations[0].includes('2')&&confirmations[0].includes(saved[0].title),'confirmation identifies count and recipe titles');
    confirmed=true;
    holdNextList=true;d.querySelector('.nav-link[data-view="home"]').click();
    await waitFor(()=>typeof releaseList==='function');
    const bulkButton=d.querySelector('#delete-selected');
    bulkButton.click();bulkButton.click();
    assert.equal(bulkButton.disabled,true,'duplicate bulk clicks are disabled');
    assert.equal(toggle.disabled,true,'selection mode cannot change mid-delete');
    assert.ok([...d.querySelectorAll('.recipe-select')].every(input=>input.disabled));
    await waitFor(()=>!bulkButton.disabled);
    releaseList();await new Promise(resolve=>setTimeout(resolve,0));
    assert.deepEqual(deleted,['a','b'],'only the frozen selection is requested once');
    assert.deepEqual(saved.map(r=>r.id),['b','c']);
    assert.equal(d.querySelectorAll('.recipe-card').length,2);
    assert.equal(d.querySelector('[data-select-id="b"]').checked,true,'failure stays selected');
    assert.equal(d.querySelector('[data-select-id="c"]').checked,false,'unselected recipe stays untouched');
    assert.ok(d.querySelector('#bulk-delete-message').textContent.includes('실패 1'));
    assert.ok(d.querySelector('#bulk-delete-message').textContent.includes('검색 저장소 연결 실패'));
    failures.clear();bulkButton.click();
    await waitFor(()=>d.querySelectorAll('.recipe-card').length===1&&!toggle.disabled);
    assert.deepEqual(deleted,['a','b','b'],'retry deletes only failed selection');
    assert.equal(saved[0].id,'c');
    assert.equal(toggle.getAttribute('aria-pressed'),'false');
    toggle.click();d.querySelector('#select-all-recipes').click();toggle.click();
    assert.equal(d.querySelectorAll('.recipe-select').length,0,'cancel selection mode clears checkbox UI');
    toggle.click();
    assert.equal(d.querySelector('#delete-selected').disabled,true,'reopening selection starts empty');
    d.querySelector('#select-all-recipes').click();
    saved=[];d.querySelector('.nav-link[data-view="home"]').click();
    await waitFor(()=>d.querySelector('#empty-import'));
    assert.equal(toggle.disabled,true,'empty list has no selection action');
    assert.equal(d.querySelector('#selection-controls').hidden,true);
    assert.deepEqual(deleted,['a','b','b'],'refresh never deletes stale selection');
    saved=[{...row,id:'c',title:'마지막 요리'}];
    d.querySelector('.nav-link[data-view="home"]').click();
    await waitFor(()=>!toggle.disabled);
    toggle.click();d.querySelector('#select-all-recipes').click();
    d.querySelector('#delete-selected').click();
    await waitFor(()=>d.querySelector('#empty-import'));
    assert.equal(saved.length,0,'select-all deletion can empty the library');
    assert.equal(d.activeElement,d.querySelector('#empty-import'),'focus must move to an enabled action after deleting the last recipe');
    console.log('PASS: bulk selection, escaping, select/clear all, cancel, partial failure, retry, duplicate clicks, untouched recipes, empty list');
  } finally { w.close(); }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
