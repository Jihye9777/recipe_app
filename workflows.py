"""Two deterministic LangGraph workflows with durable ingestion checkpoints."""
import hashlib
import re
import sqlite3
import uuid
from typing import TypedDict
from urllib.parse import urlparse, parse_qs
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver
from domain import Recipe, SearchInput, normalize, canonical, quality, semantic
from storage import public

class State(TypedDict, total=False):
    """두 LangGraph가 노드 사이에서 공유하는 부분 상태.

    수집 그래프는 ``job_id``부터 ``row``·``vector``·``result``까지 단계별로
    채우고, 검색 그래프는 ``request``·``pantry``·``candidates``·``ranked``를
    채운다. ``total=False``이므로 모든 키는 특정 단계 이전까지 선택 사항이다.
    """
    job_id: str
    url: str
    text: str
    key: str
    video_id: str
    transcript: str
    raw_transcript: str
    recipe: dict
    issues: list[str]
    row: dict
    result: dict
    vector: list[float]
    index_error: str
    request: dict
    pantry: list[str]
    candidates: list[dict]
    ranked: list[dict]
    warnings: list[str]
    user_reviewed: bool

def valid_video(url):
    """허용된 YouTube URL을 검증하고 11자리 영상 ID를 추출한다.

    Args:
        url: 일반 watch, youtu.be 공유, shorts, embed 또는 live 형식의 URL.

    Returns:
        영문·숫자·밑줄·하이픈으로 구성된 11자리 영상 ID 문자열.

    Raises:
        ValueError: HTTP(S)가 아니거나 YouTube 호스트가 아니거나 영상 ID
            형식이 올바르지 않을 때.
    """
    p = urlparse(url)
    if p.scheme not in {'https','http'} or p.hostname not in {'youtube.com','www.youtube.com','m.youtube.com','youtu.be'}:
        raise ValueError('YouTube 주소만 사용할 수 있어요.')
    id = p.path.strip('/') if p.hostname == 'youtu.be' else parse_qs(p.query).get('v',[''])[0]
    if not id and p.path.startswith(('/shorts/','/embed/','/live/')): id = p.path.split('/')[2]
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', id): raise ValueError('영상 ID가 올바르지 않아요.')
    return id

class Pipelines:
    """레시피 수집과 검색을 실행하는 두 개의 결정적 LangGraph 묶음."""

    def __init__(self, store, llm, index, extract, checkpoint_path):
        """의존성을 연결하고 수집·검색 그래프를 컴파일한다.

        Args:
            store: SQLite 읽기·쓰기를 담당하는 :class:`storage.Store`.
            llm: 레시피 생성, 임베딩, 팁 생성을 제공하는 Ollama 어댑터.
            index: upsert와 의미 검색을 제공하는 벡터 인덱스.
            extract: YouTube URL을 받아 ``(본문, 언어코드, 출처설명)``을
                반환하는 자막 추출 callable.
            checkpoint_path: 수집 그래프 체크포인트 SQLite 파일 경로.

        Side Effects:
            체크포인트 DB 연결을 열고 LangGraph 두 개를 컴파일한다. 호출자는
            서버 종료 시 ``checkpoint_db.close()``를 호출해야 한다.
        """
        self.store, self.llm, self.index, self.extract = store,llm,index,extract
        self.checkpoint_db = sqlite3.connect(checkpoint_path,check_same_thread=False)
        self.checkpointer = SqliteSaver(self.checkpoint_db)
        g = StateGraph(State)
        nodes = {'validate_url':self.validate, 'extract_transcript':self.collect,
            'preprocess':self.preprocess,'structure':self.structure,'normalize':self.normal,
            'repair':self.repair,'review':self.review,'persist':self.persist,
            'embed':self.embed,'index':self.index_row}
        for name, fn in nodes.items():
            g.add_node(name,self.tracked(name,fn))
        g.add_edge(START,'validate_url')
        g.add_conditional_edges('validate_url',lambda s: END if s.get('row') else 'extract_transcript')
        g.add_edge('extract_transcript','preprocess'); g.add_edge('preprocess','structure')
        g.add_edge('structure','normalize')
        g.add_conditional_edges('normalize',lambda s:'repair' if s['issues'] else 'persist')
        g.add_edge('repair','review'); g.add_edge('review','persist')
        g.add_edge('persist','embed'); g.add_edge('embed','index'); g.add_edge('index',END)
        self.ingest = g.compile(checkpointer=self.checkpointer)
        q = StateGraph(State)
        for name,fn in [('normalize_pantry',self.normalize_pantry),('match_ingredients',self.match_ingredients),('retrieve',self.retrieve),('filter_rerank',self.rank),('explain',self.explain)]:
            q.add_node(name,fn)
        q.add_edge(START,'normalize_pantry'); q.add_edge('normalize_pantry','match_ingredients')
        q.add_edge('match_ingredients','retrieve')
        q.add_edge('retrieve','filter_rerank'); q.add_edge('filter_rerank','explain'); q.add_edge('explain',END)
        self.search = q.compile()
    def tracked(self,name,fn):
        """수집 노드 실행 전에 현재 단계명을 jobs 테이블에 기록한다.

        Args:
            name: UI에 노출할 LangGraph 노드 이름.
            fn: ``State`` 사전을 받고 상태 업데이트 사전을 반환하는 원본 함수.

        Returns:
            동일한 입출력을 유지하면서 먼저 작업 단계를 저장하는 래퍼 함수.
        """
        def node(state):
            """작업 단계를 기록한 후 감싼 노드를 실행한다.

            Args:
                state: ``job_id``를 포함한 현재 LangGraph 상태.

            Returns:
                원본 노드 ``fn``이 반환한 상태 업데이트 사전.
            """
            self.store.job(state['job_id'],stage=name)
            return fn(state)
        return node
    def validate(self,s):
        """입력 종류를 판별하고 중복 키 및 기존 레시피를 확인한다.

        Args:
            s: ``url`` 또는 ``text``와 ``job_id``를 포함한 수집 상태.

        Returns:
            ``key``, ``video_id``, 기존 ``row``와 초기 ``result`` 업데이트.
            중복 행이 있으면 그래프가 이 결과를 사용해 즉시 종료된다.

        Raises:
            ValueError: 텍스트가 60,000자를 넘거나 URL이 유효하지 않을 때.
        """
        text = s.get('text','').strip()
        if len(text)>60000: raise ValueError('텍스트를 60,000자 이하로 나누어 주세요.')
        if text: key,vid = 'text:'+hashlib.sha256(text.encode()).hexdigest(),''
        else: vid=valid_video(s['url']); key='youtube:'+vid
        row=self.store.find(key)
        return {'key':key,'video_id':vid,'row':row,'result':{'recipe':public(row),'duplicate':True} if row else {}}
    def collect(self,s):
        """직접 입력 텍스트를 선택하거나 YouTube 자막 추출기를 호출한다.

        Args:
            s: ``text``와 검증된 ``video_id``를 포함한 수집 상태.

        Returns:
            가공 전 원문을 ``raw_transcript``에 담은 상태 업데이트 사전.

        Raises:
            extract callable이 발생시키는 자막·음성 수집 관련 예외.
        """
        text=s.get('text','').strip()
        if not text: text,_,_=self.extract('https://www.youtube.com/watch?v='+s['video_id'])
        return {'raw_transcript':text}
    def preprocess(self,s):
        """원문의 연속 공백을 하나로 합치고 길이·빈 값 여부를 검사한다.

        Args:
            s: ``raw_transcript`` 문자열을 포함한 수집 상태.

        Returns:
            정리된 ``transcript`` 문자열을 포함한 상태 업데이트 사전.

        Raises:
            ValueError: 정리 후 비어 있거나 60,000자를 초과할 때.
        """
        text=re.sub(r'\s+',' ',s['raw_transcript']).strip()
        if not text: raise ValueError('추출된 텍스트가 없습니다.')
        if len(text)>60000: raise ValueError('영상이 너무 깁니다. 필요한 자막 부분을 직접 입력해 주세요.')
        return {'transcript':text}
    def structure(self,s):
        """Ollama로 원문을 구조화하고 Recipe 스키마를 1차 검증한다.

        Args:
            s: 전처리된 ``transcript``를 포함한 수집 상태.

        Returns:
            성공하면 ``recipe`` 사전과 빈 ``issues``. Pydantic 값 검증에
            실패하면 빈 recipe와 오류 설명을 포함한 issues를 반환한다.

        Raises:
            네트워크 오류 등 ``ValueError``가 아닌 Ollama 예외는 상위 실행기로
            전파된다.
        """
        try:
            r=Recipe.model_validate(self.llm.recipe(s['transcript'])).model_dump()
            return {'recipe':r,'issues':[]}
        except ValueError as error:
            return {'recipe':{},'issues':['JSON 구조 검증 실패: '+str(error)[:1000]]}
    def normal(self,s):
        """재료명·단위를 정규화하고 원문 근거 품질을 검사한다.

        Args:
            s: ``recipe``, ``issues``, ``transcript``를 포함한 수집 상태.

        Returns:
            정규화된 recipe와 :func:`domain.quality` 문제 목록. 앞 단계에서
            recipe가 비었다면 기존 문제 목록만 유지한다.
        """
        if not s['recipe']: return {'issues':s['issues']}
        r=normalize(s['recipe'])
        return {'recipe':r,'issues':quality(r,s['transcript'])}
    def repair(self,s):
        """품질 문제를 피드백으로 전달해 LLM 재구조화를 한 번 시도한다.

        Args:
            s: 원문 ``transcript``와 기존 ``issues``를 포함한 상태.

        Returns:
            성공하면 다시 정규화·검사한 recipe와 issues. 실패하면 기존
            issues에 최대 300자의 재검토 오류를 추가한다.
        """
        try:
            r=normalize(self.llm.recipe(s['transcript'],'; '.join(s['issues'])))
            return {'recipe':r,'issues':quality(r,s['transcript'])}
        except Exception as error:
            return {'issues':s['issues']+['재검토 실패: '+str(error)[:300]]}
    def review(self,s):
        """남은 품질 문제가 있을 때 LangGraph를 사용자 확인 상태로 중단한다.

        Args:
            s: recipe, issues, transcript를 포함한 수집 상태.

        Returns:
            문제가 없으면 빈 업데이트. 승인 재개 시 사용자가 수정한 recipe,
            빈 issues, ``user_reviewed=True``를 반환한다.

        Raises:
            ValueError: 사용자가 저장을 승인하지 않았을 때 또는 수정 결과가
                Recipe 스키마를 통과하지 못할 때.

        Side Effects:
            확인이 필요하면 ``interrupt``를 호출해 체크포인트에 상태를 남긴다.
        """
        if not s['issues']: return {}
        answer=interrupt({'recipe':s['recipe'],'issues':s['issues'],'transcript':s['transcript']})
        if not answer.get('approved'): raise ValueError('저장이 취소되었습니다.')
        r=normalize(answer.get('recipe') or s['recipe'])
        return {'recipe':r,'issues':[], 'user_reviewed':True}
    def persist(self,s):
        """시맨틱 파생 정보를 만들고 SQLite 원본 레시피를 저장한다.

        Args:
            s: key, recipe, transcript, URL 및 사용자 검토 여부를 포함한 상태.

        Returns:
            저장되었거나 중복으로 이미 존재한 SQLite ``row``를 포함한 사전.

        Side Effects:
            ``recipes`` 테이블에 pending 인덱스 상태로 행을 삽입할 수 있다.
        """
        sem=semantic(s['recipe'],s['transcript'])
        sem['review_status']='user_confirmed' if s.get('user_reviewed') else 'automated_checks_passed'
        row=self.store.save(str(uuid.uuid5(uuid.NAMESPACE_URL,s['key'])),s['key'],s.get('url',''),s['raw_transcript'],
            s['recipe'],sem,self.llm.model)
        return {'row':row}
    def embed(self,s):
        """레시피 검색 문자열의 임베딩을 생성하되 실패를 원본 손실로 만들지 않는다.

        Args:
            s: ``semantic.search_text``를 가진 SQLite ``row`` 포함 상태.

        Returns:
            성공 시 ``vector``와 빈 ``index_error``. 실패 시 빈 vector와 오류
            문자열을 반환하며 예외를 전파하지 않는다.
        """
        try: return {'vector':self.llm.embed(s['row']['semantic']['search_text']),'index_error':''}
        except Exception as e: return {'index_error':str(e),'vector':[]}
    def index_row(self,s):
        """벡터를 인덱스에 upsert하고 SQLite 인덱스 상태를 확정한다.

        Args:
            s: SQLite ``row``, ``vector`` 및 선택적인 ``index_error`` 포함 상태.

        Returns:
            공개 recipe, 인덱스 오류, AI 활성화 여부와 모델명을 ``result``에
            담은 상태 업데이트 사전.

        Side Effects:
            Qdrant point를 쓰고 ``recipes.index_*`` 열을 갱신한다. Qdrant 실패는
            ``failed``로 기록하며 SQLite 원본은 유지한다.
        """
        error=s.get('index_error','')
        if not error:
            try: self.index.upsert(s['row'],s['vector'])
            except Exception as e: error=str(e)
        self.store.indexed(s['row']['id'],'failed' if error else 'indexed',error or None,
            self.index.backend,self.llm.embedding_model)
        row=self.store.get(s['row']['id'])
        return {'result':{'recipe':public(row),'index_error':error,'aiEnabled':True,'provider':self.llm.model}}
    def reindex(self,id):
        """SQLite 레시피 한 건을 다시 임베딩하고 Qdrant에 저장한다.

        Args:
            id: 재색인할 레시피 UUID 문자열.

        Returns:
            ``recipe``, ``index_error``, 모델 정보가 포함된 결과 사전.

        Raises:
            ValueError: 해당 UUID의 SQLite 원본이 없을 때.
        """
        row=self.store.get(id)
        if not row: raise ValueError('레시피가 없습니다.')
        return self.index_row({'row':row,**self.embed({'row':row})})['result']
    def reindex_all(self):
        """상태·백엔드·모델이 현재 구성과 다른 모든 레시피를 재색인한다.

        Returns:
            대상 수 ``total``, 성공 수 ``indexed``, 실패 수 ``failed``와
            실패별 ``id``·``error`` 목록을 포함한 요약 사전.

        Side Effects:
            대상마다 Ollama 임베딩, Qdrant upsert, SQLite 상태 갱신을 수행한다.
        """
        rows=self.store.needs_index(self.index.backend,self.llm.embedding_model)
        indexed=0; failures=[]
        for row in rows:
            result=self.index_row({'row':row,**self.embed({'row':row})})['result']
            if result['index_error']: failures.append({'id':row['id'],'error':result['index_error']})
            else: indexed+=1
        return {'total':len(rows),'indexed':indexed,'failed':len(failures),'failures':failures}
    def run(self,id,payload=None,resume=None):
        """체크포인트를 사용해 수집 그래프를 새로 실행하거나 재개한다.

        Args:
            id: jobs 행과 LangGraph ``thread_id``에 공통으로 쓰는 작업 UUID.
            payload: 새 실행 입력인 ``{'url': str, 'text': str}``. 재시작 복구
                때는 ``None``일 수 있다.
            resume: 사용자 검토 중단을 재개할 승인·수정 사전. 일반 실행 또는
                실패 재시도에서는 ``None``.

        Returns:
            반환값 없음. 최종 결과는 jobs 테이블에 저장한다.

        Side Effects:
            작업을 running, review, complete 또는 failed로 갱신하고 LangGraph
            체크포인트를 기록한다. 모든 내부 예외는 failed 상태로 변환한다.
        """
        cfg={'configurable':{'thread_id':id}}
        self.store.job(id,status='running',error=None)
        try:
            if payload is not None: self.store.job(id,payload=payload)
            if payload is None and resume is None and not self.ingest.get_state(cfg).values:
                payload=self.store.job(id).get('payload')
                if payload is None: raise ValueError('작업 원문이 없습니다. 새 분석을 시작해 주세요.')
            value=Command(resume=resume) if resume is not None else ({'job_id':id,**payload} if payload is not None else None)
            output=self.ingest.invoke(value,cfg)
            pauses=output.get('__interrupt__')
            if pauses: self.store.job(id,status='review',result=pauses[0].value)
            else: self.store.job(id,status='complete',result=output['result'])
        except Exception as e: self.store.job(id,status='failed',error=str(e))
    def normalize_pantry(self,s):
        """검색 요청을 검증하고 냉장고 재료명을 중복 없이 정규화한다.

        Args:
            s: 원시 ``request`` 사전을 포함한 검색 상태.

        Returns:
            검증된 request 사전과 정렬된 표준 pantry 목록.

        Raises:
            pydantic.ValidationError: 검색 조건의 타입·범위가 잘못됐을 때.
        """
        f=SearchInput.model_validate(s['request'])
        return {'request':f.model_dump(),'pantry':sorted({canonical(x) for x in f.pantry if x.strip()})}
    def retrieve(self,s):
        """Qdrant 의미 순위를 모든 SQLite 후보의 relevance 점수에 결합한다.

        Args:
            s: 검증된 request, pantry와 재료 일치 후보 목록을 포함한 상태.

        Returns:
            각 후보에 0~1 ``relevance``를 추가한 목록과 경고 목록. Qdrant
            실패 시 모든 relevance를 0으로 두고 SQLite 폴백 경고를 반환한다.
        """
        f=SearchInput.model_validate(s['request']); rows=s['candidates']; warnings=[]
        if not rows: return {'candidates':[], 'warnings':[]}
        query=f.query or ' '.join(s['pantry'])
        try: ids=self.index.search(query or '요리',f)
        except Exception as e: ids=[]; warnings=['의미 검색에 연결하지 못해 저장된 재료 기준으로 추천합니다.']
        scores={id:1-i/max(len(ids),1) for i,id in enumerate(ids)}
        # Include SQL candidates too, so exact pantry matches never disappear from top-k retrieval.
        return {'candidates':[{**r,'relevance':scores.get(r['id'],0)} for r in rows],'warnings':warnings}
    def match_ingredients(self,s):
        """보유 재료와 모든 SQLite 레시피의 필수 재료를 정확히 비교한다.

        Args:
            s: 정규화된 ``pantry`` 목록을 포함한 검색 상태.

        Returns:
            각 레시피 행에 부족 재료 ``missing``과 0~1 ``coverage``를 추가한
            ``candidates`` 목록. 선택 재료는 계산에서 제외한다.
        """
        pantry=set(s['pantry']); rows=[]
        for row in self.store.all():
            needed={x['name'] for x in row['recipe']['ingredients'] if not x['optional']}
            rows.append({**row,'missing':sorted(needed-pantry),'coverage':len(needed & pantry)/len(needed) if needed else 0})
        return {'candidates':rows}
    def rank(self,s):
        """하드 필터를 적용하고 재료 일치율과 의미 순위로 후보를 재정렬한다.

        Args:
            s: request와 missing, coverage, relevance가 포함된 후보 목록.

        Returns:
            필터를 통과한 상위 10개의 공개 레시피 목록을 ``ranked``에 담은
            사전. 점수는 ``0.8*coverage + 0.2*relevance``를 백분율로 표시한다.

        Notes:
            시간·맵기 값이 없는데 해당 제한이 지정되면 제외한다. 알레르기
            조건이 있으면 안전성 미검증 레시피도 보수적으로 제외한다.
        """
        f=SearchInput.model_validate(s['request']); ranked=[]
        for row in s['candidates']:
            r=row['recipe']; sem=row['semantic']; names={x['name'] for x in r['ingredients']}
            missing=row['missing']
            if f.max_time is not None and (r['time'] is None or r['time']>f.max_time): continue
            if f.min_spice is not None and (sem['spice_level'] is None or sem['spice_level']<f.min_spice): continue
            if names & {canonical(x) for x in f.exclude_ingredients}: continue
            if f.allergens and (sem['allergen_status']!='verified' or set(f.allergens)&set(sem['allergens'])): continue
            if f.tools is not None and (not r['tools'] or not set(r['tools'])<=set(f.tools)): continue
            if f.max_missing is not None and len(missing)>f.max_missing: continue
            coverage=row['coverage']
            score=0.8*coverage+0.2*row['relevance']
            ranked.append({**public(row),'missing':missing,'coverage':round(coverage*100),'score':round(score*100,2),
                'availability':'수량 확인 필요' if not missing else '부족 재료 있음'})
        ranked.sort(key=lambda x:(-x['score'],len(x['missing']),x['id']))
        return {'ranked':ranked[:10]}
    def explain(self,s):
        """선택적으로 상위 추천에 대한 Ollama 조리 팁을 생성한다.

        Args:
            s: request, ranked, pantry, warnings를 포함한 검색 상태.

        Returns:
            ``recipes``, 팁 문자열 ``tips``, 경고 목록을 가진 최종 ``result``.
            팁 옵션이 꺼졌거나 결과가 없으면 tips는 빈 문자열이다.

        Notes:
            팁 생성 실패는 검색 전체를 실패시키지 않고 경고로 변환한다.
        """
        tips=''; warnings=s['warnings']
        if s['request']['tips'] and s['ranked']:
            try: tips=self.llm.tips(s['ranked'][:3],s['pantry'])
            except Exception: warnings=warnings+['조리 팁 생성 실패. 검색 결과는 사용할 수 있습니다.']
        return {'result':{'recipes':s['ranked'],'tips':tips,'warnings':warnings}}
