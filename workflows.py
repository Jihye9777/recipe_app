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
    p = urlparse(url)
    if p.scheme not in {'https','http'} or p.hostname not in {'youtube.com','www.youtube.com','m.youtube.com','youtu.be'}:
        raise ValueError('YouTube 주소만 사용할 수 있어요.')
    id = p.path.strip('/') if p.hostname == 'youtu.be' else parse_qs(p.query).get('v',[''])[0]
    if not id and p.path.startswith(('/shorts/','/embed/','/live/')): id = p.path.split('/')[2]
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', id): raise ValueError('영상 ID가 올바르지 않아요.')
    return id

class Pipelines:
    def __init__(self, store, llm, index, extract, checkpoint_path):
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
        def node(state):
            self.store.job(state['job_id'],stage=name)
            return fn(state)
        return node
    def validate(self,s):
        text = s.get('text','').strip()
        if len(text)>60000: raise ValueError('텍스트를 60,000자 이하로 나누어 주세요.')
        if text: key,vid = 'text:'+hashlib.sha256(text.encode()).hexdigest(),''
        else: vid=valid_video(s['url']); key='youtube:'+vid
        row=self.store.find(key)
        return {'key':key,'video_id':vid,'row':row,'result':{'recipe':public(row),'duplicate':True} if row else {}}
    def collect(self,s):
        text=s.get('text','').strip()
        if not text: text,_,_=self.extract('https://www.youtube.com/watch?v='+s['video_id'])
        return {'raw_transcript':text}
    def preprocess(self,s):
        text=re.sub(r'\s+',' ',s['raw_transcript']).strip()
        if not text: raise ValueError('추출된 텍스트가 없습니다.')
        if len(text)>60000: raise ValueError('영상이 너무 깁니다. 필요한 자막 부분을 직접 입력해 주세요.')
        return {'transcript':text}
    def structure(self,s):
        try:
            r=Recipe.model_validate(self.llm.recipe(s['transcript'])).model_dump()
            return {'recipe':r,'issues':[]}
        except ValueError as error:
            return {'recipe':{},'issues':['JSON 구조 검증 실패: '+str(error)[:1000]]}
    def normal(self,s):
        if not s['recipe']: return {'issues':s['issues']}
        r=normalize(s['recipe'])
        return {'recipe':r,'issues':quality(r,s['transcript'])}
    def repair(self,s):
        try:
            r=normalize(self.llm.recipe(s['transcript'],'; '.join(s['issues'])))
            return {'recipe':r,'issues':quality(r,s['transcript'])}
        except Exception as error:
            return {'issues':s['issues']+['재검토 실패: '+str(error)[:300]]}
    def review(self,s):
        if not s['issues']: return {}
        answer=interrupt({'recipe':s['recipe'],'issues':s['issues'],'transcript':s['transcript']})
        if not answer.get('approved'): raise ValueError('저장이 취소되었습니다.')
        r=normalize(answer.get('recipe') or s['recipe'])
        return {'recipe':r,'issues':[], 'user_reviewed':True}
    def persist(self,s):
        sem=semantic(s['recipe'],s['transcript'])
        sem['review_status']='user_confirmed' if s.get('user_reviewed') else 'automated_checks_passed'
        row=self.store.save(str(uuid.uuid5(uuid.NAMESPACE_URL,s['key'])),s['key'],s.get('url',''),s['raw_transcript'],
            s['recipe'],sem,self.llm.model)
        return {'row':row}
    def embed(self,s):
        try: return {'vector':self.llm.embed(s['row']['semantic']['search_text']),'index_error':''}
        except Exception as e: return {'index_error':str(e),'vector':[]}
    def index_row(self,s):
        error=s.get('index_error','')
        if not error:
            try: self.index.upsert(s['row'],s['vector'])
            except Exception as e: error=str(e)
        self.store.indexed(s['row']['id'],'failed' if error else 'indexed',error or None)
        row=self.store.get(s['row']['id'])
        return {'result':{'recipe':public(row),'index_error':error,'aiEnabled':True,'provider':self.llm.model}}
    def reindex(self,id):
        row=self.store.get(id)
        if not row: raise ValueError('레시피가 없습니다.')
        return self.index_row({'row':row,**self.embed({'row':row})})['result']
    def run(self,id,payload=None,resume=None):
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
        f=SearchInput.model_validate(s['request'])
        return {'request':f.model_dump(),'pantry':sorted({canonical(x) for x in f.pantry if x.strip()})}
    def retrieve(self,s):
        f=SearchInput.model_validate(s['request']); rows=s['candidates']; warnings=[]
        if not rows: return {'candidates':[], 'warnings':[]}
        query=f.query or ' '.join(s['pantry'])
        try: ids=self.index.search(query or '요리',f)
        except Exception as e: ids=[]; warnings=['의미 검색에 연결하지 못해 저장된 재료 기준으로 추천합니다.']
        scores={id:1-i/max(len(ids),1) for i,id in enumerate(ids)}
        # Include SQL candidates too, so exact pantry matches never disappear from top-k retrieval.
        return {'candidates':[{**r,'relevance':scores.get(r['id'],0)} for r in rows],'warnings':warnings}
    def match_ingredients(self,s):
        pantry=set(s['pantry']); rows=[]
        for row in self.store.all():
            needed={x['name'] for x in row['recipe']['ingredients'] if not x['optional']}
            rows.append({**row,'missing':sorted(needed-pantry),'coverage':len(needed & pantry)/len(needed) if needed else 0})
        return {'candidates':rows}
    def rank(self,s):
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
        tips=''; warnings=s['warnings']
        if s['request']['tips'] and s['ranked']:
            try: tips=self.llm.tips(s['ranked'][:3],s['pantry'])
            except Exception: warnings=warnings+['조리 팁 생성 실패. 검색 결과는 사용할 수 있습니다.']
        return {'result':{'recipes':s['ranked'],'tips':tips,'warnings':warnings}}
