const sampleRecipes = [
  { id: 'r1', title: '버터 간장 계란밥', category: '한 그릇', time: 10, ingredients: ['밥', '달걀', '버터', '간장', '쪽파'], steps: ['따뜻한 밥을 그릇에 담아요.', '버터에 달걀 프라이를 부쳐요.', '밥 위에 달걀을 올리고 간장과 쪽파를 더해요.'], palette: ['#d7a548','#f5cf69','#76502d'], emoji: '🍳' },
  { id: 'r2', title: '들깨 감자 수제비', category: '따뜻한 국물', time: 35, ingredients: ['감자', '애호박', '대파', '수제비', '들깨가루'], steps: ['감자와 애호박을 먹기 좋게 썰어요.', '육수에 감자를 먼저 끓여요.', '수제비와 채소, 들깨가루를 넣어 마무리해요.'], palette: ['#96a06b','#d8c58d','#766746'], emoji: '🥔' },
  { id: 'r3', title: '토마토 바질 파스타', category: '주말 요리', time: 25, ingredients: ['파스타면', '토마토', '마늘', '바질', '올리브유'], steps: ['면을 알맞게 삶아요.', '올리브유에 마늘과 토마토를 볶아요.', '면과 바질을 넣고 소스가 배도록 섞어요.'], palette: ['#c33e2f','#ed7555','#5d7a43'], emoji: '🍝' }
];

let recipes = JSON.parse(localStorage.getItem('hanip-recipes') || 'null') || sampleRecipes;
let pantry = JSON.parse(localStorage.getItem('hanip-pantry') || 'null') || ['달걀', '감자', '대파'];

const qs = (selector) => document.querySelector(selector);
const qsa = (selector) => [...document.querySelectorAll(selector)];

function saveState() {
  localStorage.setItem('hanip-recipes', JSON.stringify(recipes));
  localStorage.setItem('hanip-pantry', JSON.stringify(pantry));
}

function showView(name) {
  qsa('.view').forEach((el) => el.classList.toggle('active', el.id === `${name}-view`));
  qsa('.nav-link').forEach((el) => el.classList.toggle('active', el.dataset.view === name));
  if (name === 'home') renderRecipes();
  if (name === 'pantry') renderPantry();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function renderRecipes() {
  qs('#recipe-count').textContent = `${recipes.length}개의 레시피`;
  qs('#recipe-grid').innerHTML = recipes.map((recipe, i) => `
    <article class="recipe-card" style="--card-bg:linear-gradient(145deg, ${recipe.palette[2]}, ${recipe.palette[0]}); --food-a:${recipe.palette[0]}; --food-b:${recipe.palette[1]}; --food-c:${recipe.palette[2]}">
      <div class="card-emoji" aria-hidden="true">${recipe.emoji || '🍽️'}</div>
      <div class="recipe-meta"><span>${recipe.category}</span><span>${recipe.time}분</span></div>
      <h3>${recipe.title}</h3>
      <p>${recipe.ingredients.slice(0, 4).join(' · ')}</p>
    </article>
  `).join('');
}

async function analyzeVideo(url, text = '') {
  qs('#analysis-area').innerHTML = `<div class="analysis-loading"><div class="loader"></div><strong>영상 속 요리 흐름을 읽고 있어요</strong><p>재료와 순서를 보기 좋게 다듬는 중입니다.</p></div>`;
  try {
    const response = await fetch('/api/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url, text }) });
    const rawPayload = await response.text();
    let payload;
    try {
      payload = JSON.parse(rawPayload);
    } catch {
      throw new Error(`앱 서버가 빈 응답을 보냈어요. 서버를 한 번만 실행한 뒤 다시 시도해 주세요. (HTTP ${response.status})`);
    }
    if (!response.ok) throw new Error(payload.error || '분석에 실패했어요.');
    const parsed = payload.recipe || { title: '자막을 가져왔어요', category: '로컬 AI 연결 대기', time: 0, ingredients: ['Ollama가 실행 중인지 확인해 주세요.'], steps: ['Ollama를 켠 뒤 다시 분석해 주세요.'], palette: ['#c05b3e','#efaa62','#733a2d'], emoji: '📝' };
    Object.assign(parsed, { id: `r${Date.now()}`, palette: parsed.palette || ['#c05b3e','#efaa62','#733a2d'], emoji: parsed.emoji || '🍳', source: url });
    window.currentParsed = parsed;
    qs('#analysis-area').innerHTML = `
      <article class="analysis-result">
        <div class="result-top"><div><span class="section-kicker">${payload.aiEnabled ? `${payload.provider} 분석 완료` : '자막 수집 완료 · 로컬 AI 대기'} · 예상 ${parsed.time || '-'}분</span><h2>${parsed.title}</h2><p>${payload.source || '영상에서 추출한 텍스트'} · ${payload.language || '한국어'}</p></div><button class="save-button" id="save-parsed">내 레시피 북에 저장</button></div>
        <div class="result-columns"><div><h3>준비할 재료</h3><ul>${parsed.ingredients.map((x) => `<li>${x}</li>`).join('')}</ul></div><div><h3>조리 순서</h3><ol>${parsed.steps.map((x) => `<li>${x}</li>`).join('')}</ol></div></div>
      </article>`;
    qs('#save-parsed').addEventListener('click', () => {
      if (!recipes.some((r) => r.id === parsed.id)) recipes.unshift(parsed);
      saveState();
      toast('레시피 북에 저장했어요');
      setTimeout(() => showView('home'), 500);
    });
  } catch (error) {
    const blocked = error.message.includes('page needs to be reloaded');
    qs('#analysis-area').innerHTML = `<div class="analysis-result"><div class="result-top"><div><span class="section-kicker">분석을 시작하지 못했어요</span><h2>${blocked ? 'YouTube가 자동 요청을 막았어요' : '자막을 확인해 주세요'}</h2><p>${error.message}</p></div></div><p class="helper">${blocked ? '아래 텍스트 붙여넣기 입력란에 영상 스크립트나 설명란의 레시피를 넣으면 바로 Ollama로 정리할 수 있어요.' : '자막이 공개된 YouTube 영상인지, 주소가 올바른지 확인한 뒤 다시 시도해 주세요.'}</p></div>`;
  }
}

function renderPantry() {
  const quick = ['양파', '마늘', '두부', '밥', '토마토', '버터'];
  qs('#quick-add').innerHTML = quick.filter((x) => !pantry.includes(x)).map((x) => `<button data-add="${x}">+ ${x}</button>`).join('');
  qs('#ingredient-tags').innerHTML = pantry.length ? pantry.map((x) => `<button class="ingredient-tag" data-remove="${x}" title="클릭해서 빼기">${x} ×</button>`).join('') : '<p class="helper">재료를 하나씩 추가해보세요.</p>';
  qs('#quick-add').querySelectorAll('button').forEach((b) => b.onclick = () => addIngredient(b.dataset.add));
  qs('#ingredient-tags').querySelectorAll('button').forEach((b) => b.onclick = () => { pantry = pantry.filter((x) => x !== b.dataset.remove); saveState(); renderPantry(); });
  renderRecommendations();
}

function normalizeIngredient(value) { return value.replace(/[0-9/]+|큰술|작은술|약간|모|개|대/g, '').trim(); }

function renderRecommendations() {
  const ranked = recipes.map((recipe) => {
    const normalized = recipe.ingredients.map(normalizeIngredient);
    const matches = normalized.filter((ingredient) => pantry.some((p) => ingredient.includes(p) || p.includes(ingredient)));
    return { ...recipe, matches: matches.length, missing: normalized.filter((x) => !matches.includes(x)), score: Math.round(matches.length / normalized.length * 100) };
  }).sort((a, b) => b.score - a.score);
  qs('#recommendations').innerHTML = ranked.map((r, i) => `
    <article class="recommend-item"><div class="recommend-thumb" style="--thumb:${r.palette[1]}55">${r.emoji || '🍽️'}</div><div><h3>${i === 0 && r.score > 0 ? '가장 잘 맞아요 · ' : ''}${r.title}</h3><p>${r.missing.length ? `더 있으면 좋아요: ${r.missing.slice(0, 3).join(', ')}` : '지금 바로 만들 수 있어요!'}</p></div><div class="match"><strong>${r.score}%</strong>재료 일치</div></article>
  `).join('');
}

function addIngredient(value) {
  const cleaned = value.trim();
  if (cleaned && !pantry.includes(cleaned)) pantry.push(cleaned);
  saveState(); renderPantry();
}

function toast(message) {
  const el = qs('#toast'); el.textContent = message; el.classList.add('show');
  clearTimeout(window.toastTimer); window.toastTimer = setTimeout(() => el.classList.remove('show'), 2200);
}

async function refreshLlmStatus() {
  const badge = qs('#llm-status');
  if (!badge) return;
  try {
    const response = await fetch('/api/status');
    const status = await response.json();
    badge.className = `llm-status ${status.running && status.modelInstalled ? 'online' : 'offline'}`;
    badge.innerHTML = `<i></i>${status.running && status.modelInstalled ? `로컬 AI 연결됨 · ${status.model}` : status.running ? 'Ollama 실행 중 · 모델 확인 필요' : '로컬 AI 연결 안 됨'}`;
    badge.title = status.running ? `Ollama 포트 11434 · ${status.model}` : 'Ollama가 실행 중인지 확인해 주세요.';
  } catch {
    badge.className = 'llm-status offline'; badge.innerHTML = '<i></i>상태 확인 실패';
  }
}

qsa('[data-view]').forEach((el) => el.addEventListener('click', () => showView(el.dataset.view)));
qs('#open-import').addEventListener('click', () => showView('import'));
qs('#url-form').addEventListener('submit', (event) => { event.preventDefault(); analyzeVideo(qs('#youtube-url').value); });
qs('#text-form').addEventListener('submit', (event) => { event.preventDefault(); const text = qs('#source-text').value.trim(); if (text) analyzeVideo('', text); else toast('붙여 넣을 텍스트를 입력해 주세요.'); });
qs('#ingredient-form').addEventListener('submit', (event) => { event.preventDefault(); addIngredient(qs('#ingredient-input').value); qs('#ingredient-input').value = ''; });
renderRecipes();
refreshLlmStatus();
setInterval(refreshLlmStatus, 5000);
