const qs = (s) => document.querySelector(s);
const qsa = (s) => [...document.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let recipes = [], pantry = [], searchVersion = 0, pollVersion = 0;
let selectionMode = false, bulkDeleting = false, recipeListVersion = 0;
let selectedRecipeIds = new Set();
async function api(path, body, method = body === undefined ? 'GET' : 'POST') {
  const response = await fetch(path, body === undefined ? {method} : {method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const raw = await response.text();
  let data;
  try { data = JSON.parse(raw); } catch { throw new Error(`서버 응답 오류 (HTTP ${response.status}). 새 서버를 실행해 주세요.`); }
  if (!response.ok) throw new Error(data.error || data.detail || '요청 실패');
  return data;
}
function toast(message) {
  qs('#toast').textContent=message; qs('#toast').classList.add('show');
  clearTimeout(window.toastTimer); window.toastTimer=setTimeout(()=>qs('#toast').classList.remove('show'),5000);
}
function showView(name) {
  qsa('.view').forEach(el=>el.classList.toggle('active',el.id===`${name}-view`));
  qsa('.nav-link').forEach(el=>{
    const active=el.dataset.view===name;
    el.classList.toggle('active',active);
    if(active) el.setAttribute('aria-current','page'); else el.removeAttribute('aria-current');
  });
  if(name==='home') refreshRecipes().catch(e=>toast(e.message));
  if(name==='pantry') renderPantry();
  window.scrollTo({top:0,behavior:window.matchMedia?.('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
}
async function refreshRecipes() {
  if(bulkDeleting) return;
  const version=++recipeListVersion;
  const out=await api('/api/recipes');
  if(version!==recipeListVersion || bulkDeleting) return;
  recipes=out.recipes; renderRecipes();
}
function updateRecipeSelection() {
  const count=selectedRecipeIds.size;
  const toggle=qs('#toggle-selection');
  toggle.disabled=bulkDeleting || !recipes.length;
  toggle.textContent=selectionMode?'선택 취소':'선택 삭제';
  toggle.setAttribute('aria-pressed',String(selectionMode));
  qs('#recipe-grid').setAttribute('aria-busy',String(bulkDeleting));
  qs('#selection-controls').hidden=!selectionMode;
  qs('#select-all-recipes').disabled=bulkDeleting || !recipes.length;
  qs('#clear-recipe-selection').disabled=bulkDeleting || !count;
  qs('#selection-count').textContent=`${count}개 선택됨`;
  qs('#delete-selected').disabled=bulkDeleting || !count;
  qs('#delete-selected').textContent=bulkDeleting?'삭제 중…':`선택한 ${count}개 삭제`;
  qsa('.recipe-select').forEach(input=>{
    input.checked=selectedRecipeIds.has(input.dataset.selectId);
    input.disabled=bulkDeleting;
  });
}
function renderRecipes() {
  const available=new Set(recipes.map(recipe=>recipe.id));
  selectedRecipeIds=new Set([...selectedRecipeIds].filter(id=>available.has(id)));
  if(!recipes.length) selectionMode=false;
  qs('#recipe-count').textContent=`${recipes.length}개의 레시피 · SQLite`;
  qs('#recipe-grid').innerHTML=recipes.map((r,i)=>`<article class="recipe-card${selectionMode?' selecting':''}" data-index="${i}" ${selectionMode?'':'tabindex="0" role="button"'}>${selectionMode?`<label class="recipe-select-label"><input class="recipe-select" type="checkbox" data-select-id="${esc(r.id)}" aria-label="${esc(r.title)} 삭제 대상으로 선택" />삭제할 레시피 선택</label>`:''}<span class="recipe-number">DIARY / ${String(i+1).padStart(2,'0')}</span><div class="recipe-meta"><span>${esc(r.category)}</span><span>${r.time ? esc(r.time)+'분':'시간 미상'}</span></div><h3>${esc(r.title)}</h3><p>${esc(r.ingredients.slice(0,4).join(' · '))}</p><span class="card-open">${selectionMode?'체크박스로 선택하세요':'요리 일기 펼쳐보기 <span aria-hidden="true">↗</span>'}</span></article>`).join('') || '<div class="empty-state"><span class="section-kicker">YOUR FIRST PAGE</span><h3>첫 요리 일기를 기다리고 있어요</h3><p>다시 만들고 싶은 레시피로 첫 페이지를 채워보세요.</p><button class="primary-button" id="empty-import">첫 레시피 담기</button></div>';
  if(qs('#empty-import')) qs('#empty-import').onclick=()=>showView('import');
  qsa('#recipe-grid [data-index]').forEach(el=>{
    if(selectionMode) return;
    const open=()=>showSavedRecipe(recipes[Number(el.dataset.index)]);
    el.onclick=open; el.onkeydown=e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();open();}};
  });
  qsa('.recipe-select').forEach(input=>input.onchange=()=>{
    if(bulkDeleting) return;
    if(input.checked) selectedRecipeIds.add(input.dataset.selectId);
    else selectedRecipeIds.delete(input.dataset.selectId);
    updateRecipeSelection();
  });
  updateRecipeSelection();
}
async function deleteSelectedRecipes() {
  if(bulkDeleting) return;
  const chosen=recipes.filter(recipe=>selectedRecipeIds.has(recipe.id));
  if(!chosen.length) return;
  const titles=chosen.slice(0,5).map(recipe=>'• '+recipe.title).join('\n');
  const more=chosen.length>5?`\n외 ${chosen.length-5}개`:'';
  if(!window.confirm(`선택한 ${chosen.length}개 레시피를 삭제할까요?\n${titles}${more}\n원본 레시피와 검색 데이터가 삭제되며 복구할 수 없어요.`)) return;
  bulkDeleting=true; ++recipeListVersion; updateRecipeSelection();
  const deleted=new Set(), failures=[];
  try {
    for(const recipe of chosen) {
      qs('#bulk-delete-message').textContent=`삭제 처리 중: ${deleted.size+failures.length} / ${chosen.length}개`;
      try {
        await api('/api/recipes/'+encodeURIComponent(recipe.id),undefined,'DELETE');
        deleted.add(recipe.id);
      } catch(error) { failures.push({recipe,error:error.message}); }
    }
  } finally {
    bulkDeleting=false;
    recipes=recipes.filter(recipe=>!deleted.has(recipe.id));
    selectedRecipeIds=new Set(failures.map(item=>item.recipe.id));
    selectionMode=failures.length>0;
    if(deleted.size) {
      const detail=qs('#analysis-area .analysis-result');
      if(detail && deleted.has(detail.dataset.recipeId)) qs('#analysis-area').innerHTML='';
      ++searchVersion; qs('#recommendations').innerHTML='';
    }
    renderRecipes();
    const errors=failures.slice(0,3).map(item=>`${item.recipe.title}: ${item.error}`).join('\n');
    qs('#bulk-delete-message').textContent=`${deleted.size}개 삭제 완료 · 실패 ${failures.length}개${errors?'\n'+errors+'\n실패한 항목은 선택된 상태로 남아 있어요. 다시 시도해 주세요.':''}`;
    if(qs('#home-view').classList.contains('active')) {
      const target=failures.length?qs('#delete-selected'):(recipes.length?qs('#toggle-selection'):qs('#empty-import'));
      target?.focus();
    }
  }
}
function showSavedRecipe(r) {
  showView('import');
  qs('#analysis-area').innerHTML=`<article class="analysis-result"><div class="result-top"><div><span class="section-kicker">SQLite에 저장됨 · 검색 인덱스: ${esc(r.index_status)}</span><h2>${esc(r.title)}</h2><p>${esc(r.category)} · ${r.time ? esc(r.time)+'분':'시간 미상'}</p></div><button class="save-button" id="back-to-recipes">내 요리 일기로</button></div><div class="result-columns"><div><h3>준비할 재료</h3><ul>${r.ingredients.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div><div><h3>조리 순서</h3><ol>${r.steps.map(x=>`<li>${esc(x)}</li>`).join('')}</ol></div></div><p class="helper">매운맛: ${r.semantic.spice_level ?? '알 수 없음'} (재료 기반 추정) · 알레르기 안전성은 검증되지 않았습니다.</p><button class="text-button" id="reindex">검색 인덱스 다시 만들기</button><p id="index-message" role="status"></p></article>`;
  qs('#back-to-recipes').onclick=()=>showView('home');
  qs('#analysis-area .analysis-result').dataset.recipeId=r.id;
  qs('#analysis-area .analysis-result').insertAdjacentHTML('beforeend','<button class="text-button danger-button" id="delete-recipe" type="button">레시피 삭제</button>');
  qs('#delete-recipe').onclick=async e=>{
    if(!window.confirm(`“${r.title}” 레시피를 삭제할까요?\n원본 레시피와 검색 데이터가 삭제되며 복구할 수 없어요.`)) return;
    const button=e.currentTarget;
    button.disabled=true; button.textContent='삭제 중…'; qs('#reindex').disabled=true;
    try {
      await api('/api/recipes/'+encodeURIComponent(r.id),undefined,'DELETE');
      recipes=recipes.filter(recipe=>recipe.id!==r.id); renderRecipes();
      qs('#analysis-area').innerHTML='';
      ++searchVersion; qs('#recommendations').innerHTML='';
      showView('home'); qs('#main-content').focus({preventScroll:true});
      toast('레시피를 삭제했어요.');
    } catch(error) {
      toast(error.message); button.disabled=false; button.textContent='레시피 삭제';
      if(qs('#reindex')) qs('#reindex').disabled=false;
    }
  };
  qs('#reindex').onclick=async e=>{
    e.target.disabled=true; qs('#delete-recipe').disabled=true;
    try { const out=await api('/api/reindex',{id:r.id}); showSavedRecipe(out.recipe); qs('#index-message').textContent=out.index_error ? `원본은 보존됨. 인덱스 실패: ${out.index_error}`:'검색 인덱스 저장 완료'; }
    catch(error){toast(error.message);e.target.disabled=false;if(qs('#delete-recipe'))qs('#delete-recipe').disabled=false;}
  };
}
const stages={validate_url:'URL·중복 확인',extract_transcript:'자막 추출 / Whisper',preprocess:'자막 전처리',structure:'LLM 구조화·검증',normalize:'재료 정규화·품질 검사',repair:'LLM 재검토',review:'사용자 확인',persist:'SQLite 저장',embed:'임베딩 생성',index:'Qdrant Local 인덱싱'};
function failure(error,id) {
  qs('#analysis-area').innerHTML=`<div class="analysis-result"><h2>처리를 완료하지 못했어요</h2><p>${esc(error.message)}</p><p class="helper">YouTube 수집이 막힌 경우 자막/레시피 텍스트를 직접 붙여 넣을 수 있어요.</p>${id?'<button class="text-button" id="retry-job">중단된 단계 재시도</button>':''}</div>`;
  if(id) qs('#retry-job').onclick=async()=>{try{await api('/api/retry',{job_id:id});pollJob(id);}catch(e){toast(e.message);}};
}
function showReview(job) {
  const review=job.result;
  qs('#analysis-area').innerHTML=`<div class="analysis-result"><h2>저장 전 확인이 필요해요</h2><ul>${review.issues.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><details><summary>원문 확인</summary><p>${esc(review.transcript)}</p></details><label for="review-json">레시피 JSON을 확인·수정하세요 (수량을 모르면 null)</label><textarea id="review-json" rows="18"></textarea><button class="primary-button" id="approve">내용을 확인했어요 · 저장</button></div>`;
  qs('#review-json').value=JSON.stringify(review.recipe,null,2);
  qs('#approve').onclick=async e=>{
    try { const recipe=JSON.parse(qs('#review-json').value); e.target.disabled=true; await api('/api/review',{job_id:job.id,approved:true,recipe}); pollJob(job.id); }
    catch(error){toast(error.message);e.target.disabled=false;}
  };
}
async function pollJob(id) {
  const version=++pollVersion;
  localStorage.setItem('hanip-job-id',id);
  try {
    while(version===pollVersion) {
      const job=await api('/api/jobs/'+encodeURIComponent(id));
      if(version!==pollVersion) return;
      if(job.status==='complete') {
        localStorage.removeItem('hanip-job-id'); await refreshRecipes(); showSavedRecipe(job.result.recipe);
        qs('#index-message').textContent=job.result.index_error ? `SQLite 원본은 저장되었습니다. 검색 인덱스 실패: ${job.result.index_error}` : (job.result.duplicate?'이미 저장된 레시피입니다.':'분석 및 저장 완료');
        return;
      }
      if(job.status==='review'){showReview(job);return;}
      if(job.status==='failed'){failure(new Error(job.error),id);return;}
      qs('#analysis-area').innerHTML=`<div class="analysis-loading"><div class="loader"></div><strong>${esc(stages[job.stage] || '작업 대기 중')}</strong><p>로컬 모델 속도에 따라 수 분이 걸릴 수 있어요. 새로고침해도 작업 ID로 다시 확인합니다.</p><button id="resume-job" class="text-button">서버 재시작 후 작업 재개</button></div>`;
      qs('#resume-job').onclick=async()=>{try{await api('/api/retry',{job_id:id});}catch(e){toast(e.message);}};
      await new Promise(resolve=>setTimeout(resolve,1500));
    }
  } catch(e){if(version===pollVersion)failure(e,id);}
}
async function analyzeVideo(url,text='') {
  try { const job=await api('/api/analyze',{url,text}); pollJob(job.job_id); }
  catch(e){failure(e);}
}
function renderPantry() {
  qs('#quick-add').innerHTML=['양파','마늘','두부','밥','달걀'].filter(x=>!pantry.includes(x)).map(x=>`<button data-add="${x}">+ ${x}</button>`).join('');
  qs('#ingredient-tags').innerHTML=pantry.map((x,i)=>`<button class="ingredient-tag" data-remove="${i}">${esc(x)} ×</button>`).join('');
  qsa('[data-add]').forEach(b=>b.onclick=()=>savePantry([...pantry,b.dataset.add]));
  qsa('[data-remove]').forEach(b=>b.onclick=()=>savePantry(pantry.filter((_,i)=>i!==Number(b.dataset.remove))));
  renderRecommendations();
}
async function savePantry(items) {
  try {pantry=(await api('/api/pantry',{pantry:items})).pantry;renderPantry();}catch(e){toast(e.message);}
}
const commaList = id => qs(id).value.split(',').map(x=>x.trim()).filter(Boolean);
async function renderRecommendations() {
  const version=++searchVersion;
  qs('#recommendations').textContent='저장된 레시피를 검색하고 있어요…';
  const number=id=>qs(id).value===''?null:Number(qs(id).value);
  try {
    const out=await api('/api/search',{pantry,query:qs('#search-query').value,max_time:number('#max-time'),max_missing:number('#max-missing'),min_spice:number('#min-spice'),exclude_ingredients:commaList('#exclude'),allergens:commaList('#allergens'),tools:qs('#tools').value.trim()?commaList('#tools'):null,tips:qs('#tips').checked});
    if(version!==searchVersion)return;
    qs('#recommendations').innerHTML=out.warnings.map(x=>`<p class="helper">${esc(x)}</p>`).join('')+(out.recipes.map((r,i)=>`<article class="recommend-item" data-result="${i}" tabindex="0" role="button"><div><h3>${esc(r.title)}</h3><p>${r.missing.length?'부족: '+esc(r.missing.join(', ')):'재료 종류 일치 · 수량 확인 필요'}</p></div><div class="match"><strong>${r.coverage}%</strong>재료 종류 일치</div></article>`).join('')||'<p>조건에 맞는 레시피가 없어요. 알레르기 조건은 안전성 미검증 레시피를 모두 제외합니다.</p>')+(out.tips?`<div class="analysis-result"><h3>AI 조리 팁 · 검증되지 않은 제안</h3><p>${esc(out.tips)}</p></div>`:'');
    qsa('[data-result]').forEach(el=>{el.onclick=()=>showSavedRecipe(out.recipes[Number(el.dataset.result)]);el.onkeydown=e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();el.click();}};});
  } catch(e){if(version===searchVersion)qs('#recommendations').textContent=e.message;}
}
async function refreshLlmStatus() {
  try {const s=await api('/api/status'); qs('#llm-status').className=`llm-status ${s.running&&s.modelInstalled?'online':'offline'}`;qs('#llm-status').textContent=s.running&&s.modelInstalled?`로컬 AI · ${s.model}`:'Ollama / 모델 연결 확인 필요';}
  catch {qs('#llm-status').textContent='앱 서버 연결 실패';}
}
async function refreshServiceHealth() {
  try {
    const s=await api('/api/health');
    const names={sqlite:'원본 DB',ollama:'레시피 AI',embedding:'임베딩',qdrant:'검색 DB'};
    qs('#service-health').textContent=Object.entries(names).map(([key,label])=>`${label}: ${s[key].ready?'준비됨':'연결/설치 확인 필요'}`).join(' · ');
    const button=qs('#reindex-all');
    button.hidden=!s.qdrant.ready || !s.qdrant.needsReindex;
    if(!button.hidden) button.textContent=`저장된 레시피 검색 인덱스 복구 (${s.qdrant.needsReindex}개)`;
  } catch(e){qs('#service-health').textContent=e.message;}
}
async function initialize() {
  try {
    await refreshRecipes(); pantry=(await api('/api/pantry')).pantry;
    const job=localStorage.getItem('hanip-job-id');if(job){showView('import');pollJob(job);}
  } catch(e){qs('#recipe-grid').textContent=e.message;}
}
qs('#toggle-selection').onclick=()=>{
  if(bulkDeleting) return;
  selectionMode=!selectionMode; selectedRecipeIds.clear();
  qs('#bulk-delete-message').textContent=''; renderRecipes();
  if(selectionMode) qs('.recipe-select')?.focus();
};
qs('#select-all-recipes').onclick=()=>{
  if(bulkDeleting) return;
  selectedRecipeIds=new Set(recipes.map(recipe=>recipe.id)); updateRecipeSelection();
};
qs('#clear-recipe-selection').onclick=()=>{
  if(bulkDeleting) return;
  selectedRecipeIds.clear(); updateRecipeSelection();
};
qs('#delete-selected').onclick=deleteSelectedRecipes;
qsa('[data-view]').forEach(el=>el.onclick=()=>showView(el.dataset.view));
qs('#open-import').onclick=()=>showView('import');
qs('#url-form').onsubmit=e=>{e.preventDefault();analyzeVideo(qs('#youtube-url').value);};
qs('#text-form').onsubmit=e=>{e.preventDefault();const text=qs('#source-text').value.trim();if(text)analyzeVideo('',text);};
qs('#ingredient-form').onsubmit=e=>{e.preventDefault();const v=qs('#ingredient-input').value.trim();if(v)savePantry([...pantry,v]);qs('#ingredient-input').value='';};
qs('#search-form').onsubmit=e=>{e.preventDefault();renderRecommendations();};
qs('#reindex-all').onclick=async e=>{
  e.target.disabled=true;e.target.textContent='검색 인덱스를 복구하고 있어요…';
  try{const out=await api('/api/reindex-all',{});toast(`${out.indexed}개 색인 완료 · 실패 ${out.failed}개`);await refreshRecipes();await refreshServiceHealth();}
  catch(error){toast(error.message);}
  finally{e.target.disabled=false;}
};
initialize();refreshLlmStatus();refreshServiceHealth();setInterval(refreshLlmStatus,15000);setInterval(refreshServiceHealth,30000);
