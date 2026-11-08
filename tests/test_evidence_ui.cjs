// Draft/evidence/reanalysis DOM behavior, independent of a live model.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require(process.env.RECIPE_JSDOM_PATH || '../.runtime/ui-test/node_modules/jsdom');
const root = path.resolve(__dirname, '..');
const original = {id:'old', title:'우동', source:'https://youtu.be/Vpqv2Ux_IDM', category:'요리',
  time:null, ingredients:['우유 300 ml'], steps:['우유를 넣어요.'],
  semantic:{spice_level:null,quality_issues:['단위 확인']}, quality_status:'draft', index_status:'indexed',
  sources:{video_id:'Vpqv2Ux_IDM', sources:[{id:'frame:0',kind:'screen_text',start:11,end:11,
    text:'우유 300ml <img src=x onerror=alert(1)>',readable:true}],warnings:['AI 판독 초안'],
    corrections:[{source_id:'caption:0',original:'300mm',target_source_id:'frame:0',corrected:'300ml'}]}};
const candidate = {...original,id:'new',semantic:{...original.semantic,reanalyze_of:'old'}};
async function waitFor(test) {
  for(let index=0;index<150;index++) {
    if(test()) return;
    await new Promise(resolve=>setTimeout(resolve,10));
  }
  throw new Error('DOM update timed out');
}
async function main() {
  const dom = new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),
    {url:'http://localhost:8000',runScripts:'outside-only'});
  const w = dom.window;
  w.scrollTo=()=>{};
  let saved=[original], reviewed=false, reanalyzeBody;
  w.fetch=async(url, options={})=>{
    let body;
    if(url==='/api/recipes') body={recipes:saved};
    else if(url==='/api/pantry') body={pantry:[]};
    else if(url==='/api/status') body={running:true,modelInstalled:true,model:'fake'};
    else if(url==='/api/health') body={sqlite:{ready:true},ollama:{ready:true},embedding:{ready:true},qdrant:{ready:true}};
    else if(url==='/api/search') body={recipes:[{...original,missing:[],coverage:100}],warnings:[],tips:''};
    else if(url==='/api/reanalyze') {reanalyzeBody=JSON.parse(options.body);body={job_id:'new-job'};}
    else if(url==='/api/jobs/new-job') body=reviewed?{id:'new-job',status:'complete',result:{recipe:candidate}}:
      {id:'new-job',status:'review',result:{recipe:{title:'우동',ingredients:[{name:'우유'}],steps:['넣어요']},
        issues:['화면 확인'],transcript:'원문',sources:original.sources}};
    else if(url==='/api/review') {reviewed=true;saved=[original,candidate];body={job_id:'new-job'};}
    else throw new Error('Unexpected request '+url);
    return {ok:true,status:200,text:async()=>JSON.stringify(body)};
  };
  try {
    w.eval(fs.readFileSync(path.join(root,'app.js'),'utf8'));
    await waitFor(()=>w.document.querySelector('.recipe-card'));
    await waitFor(()=>w.document.querySelector('#llm-status').textContent.includes('재시작'));
    assert.ok(w.document.querySelector('.recipe-card').textContent.includes('초안'));
    await w.renderRecommendations();
    assert.ok(w.document.querySelector('.recommend-item').textContent.includes('초안'),
      'recommendations must keep the draft status visible');
    w.document.querySelector('.recipe-card').click();
    assert.ok(w.document.querySelector('.quality-notice').textContent.includes('초안'));
    assert.ok(w.document.querySelector('.quality-issues')?.textContent.includes('단위 확인'),
      'saved drafts must expose their unresolved issues');
    assert.equal(w.document.querySelector('.source-evidence img'),null,'source content must be escaped');
    const link=w.document.querySelector('.source-evidence a');
    assert.equal(link.href,'https://www.youtube.com/watch?v=Vpqv2Ux_IDM&t=11s');
    assert.ok(w.document.querySelector('.source-evidence').textContent.includes('300mm → 300ml'));
    w.document.querySelector('#reanalyze-recipe').click();
    await waitFor(()=>w.document.querySelector('#approve'));
    assert.deepEqual(reanalyzeBody,{recipe_id:'old'});
    assert.equal(saved.length,1,'reanalysis must not replace existing original');
    assert.ok(w.document.querySelector('#approve').textContent.includes('초안 저장'));
    assert.ok(w.document.querySelector('.source-evidence a'));
    w.document.querySelector('#approve').click();
    await waitFor(()=>w.document.querySelector('#index-message')?.textContent.includes('초안 저장 완료'));
    assert.equal(saved[0],original);
    assert.equal(saved.length,2);
    assert.ok(w.document.querySelector('.quality-notice').textContent.includes('초안'));
    console.log('Evidence/draft/reanalysis DOM tests passed');
  } finally {
    dom.window.close();
  }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
