// DOM unit tests; not a substitute for a real browser/layout test.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('../.runtime/ui-test/node_modules/jsdom');
const root=path.resolve(__dirname,'..');
const recipe={id:'fixture',title:'<img src=x onerror=alert(1)> 달걀 요리',category:'요리',time:5,
  ingredients:['달걀 2 개'],steps:['프라이팬에서 익혀요.'],semantic:{spice_level:null},index_status:'failed'};
const structured={title:'달걀 요리',ingredients:[{raw_name:'달걀',name:'달걀',quantity:2,unit:'개',evidence:'달걀 2개'}],steps:['익혀요.']};
async function waitFor(fn){for(let i=0;i<150;i++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw new Error('DOM update timed out');}
async function main(){
  const dom=new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{url:'http://localhost:8000',runScripts:'outside-only'});
  const w=dom.window;w.scrollTo=()=>{};
  let saved=[recipe],pantry=[],state='review',reviewSent=null;
  const seen=[];
  w.fetch=async(url,opts={})=>{
    const body=opts.body?JSON.parse(opts.body):null;seen.push([url,body]);let out;
    if(url==='/api/recipes')out={recipes:saved};
    else if(url==='/api/pantry'){if(body)pantry=body.pantry;out={pantry};}
    else if(url==='/api/status')out={running:true,modelInstalled:true,model:'fixture'};
    else if(url==='/api/health')out={sqlite:{ready:true},ollama:{ready:true},embedding:{ready:true},qdrant:{ready:true,needsReindex:1}};
    else if(url==='/api/analyze')out={job_id:'job1'};
    else if(url==='/api/jobs/job1')out=state==='review'?{id:'job1',status:'review',result:{recipe:structured,issues:['확인 필요'],transcript:'달걀 2개'}}:{id:'job1',status:'complete',result:{recipe,index_error:'Qdrant 저장 실패'}};
    else if(url==='/api/review'){reviewSent=body;state='complete';out={job_id:'job1'};}
    else if(url==='/api/reindex')out={recipe:{...recipe,index_status:'indexed'},index_error:''};
    else if(url==='/api/reindex-all')out={total:1,indexed:1,failed:0,failures:[]};
    else if(url==='/api/search')out={recipes:[{...recipe,missing:[],coverage:100}],warnings:['재료 기준 폴백'],tips:''};
    else throw new Error('Unexpected request: '+url);
    return{ok:true,status:200,text:async()=>JSON.stringify(out)};
  };
  try{
    w.eval(fs.readFileSync(path.join(root,'app.js'),'utf8'));
    await waitFor(()=>w.document.querySelector('#recipe-grid .recipe-card'));
    assert.equal(w.document.querySelector('#recipe-grid img'),null,'recipe title must be escaped');
    w.document.querySelector('#recipe-grid .recipe-card').click();
    assert.ok(w.document.querySelector('#analysis-area').textContent.includes('SQLite에 저장됨'));
    assert.equal(w.document.querySelector('#analysis-area img'),null);
    w.document.querySelector('#reindex').click();
    await waitFor(()=>w.document.querySelector('#index-message').textContent==='검색 인덱스 저장 완료');
    w.document.querySelector('[data-view="pantry"]').click();
    await waitFor(()=>w.document.querySelector('[data-result]'));
    assert.ok(w.document.querySelector('#recommendations').textContent.includes('수량 확인 필요'));
    w.document.querySelector('#ingredient-input').value='달걀';
    w.document.querySelector('#ingredient-form').dispatchEvent(new w.Event('submit',{cancelable:true}));
    await waitFor(()=>pantry.includes('달걀'));
    w.document.querySelector('#max-missing').value='0';
    w.document.querySelector('#search-form').dispatchEvent(new w.Event('submit',{cancelable:true}));
    await waitFor(()=>seen.some(([url,b])=>url==='/api/search'&&b.max_missing===0));
    w.document.querySelector('[data-view="import"]').click();
    w.document.querySelector('#source-text').value='달걀 2개';
    w.document.querySelector('#text-form').dispatchEvent(new w.Event('submit',{cancelable:true}));
    await waitFor(()=>w.document.querySelector('#approve'));
    w.document.querySelector('#review-json').value='{invalid';w.document.querySelector('#approve').click();
    await waitFor(()=>w.document.querySelector('#toast').classList.contains('show'));
    assert.equal(reviewSent,null,'invalid JSON must not be submitted');
    w.document.querySelector('#review-json').value=JSON.stringify(structured);w.document.querySelector('#approve').click();
    await waitFor(()=>w.document.querySelector('#index-message')?.textContent.includes('SQLite 원본은 저장'));
    assert.equal(reviewSent.approved,true);
    assert.equal(w.localStorage.getItem('hanip-job-id'),null);
    assert.ok(w.document.querySelector('#service-health').textContent.includes('검색 DB: 준비됨'));
    assert.equal(w.document.querySelector('#reindex-all').hidden,false);
    console.log('PASS: SQL detail, HTML escaping, reindex, pantry, search filters, review validation/resume, saved-with-index-failure, health status');
  }finally{w.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
