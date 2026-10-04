"""레시피 수집·추천 LangGraph 및 도메인 규칙 단위 테스트."""

import copy
import tempfile
import unittest
import uuid
from pathlib import Path
from domain import Recipe, canonical, normalize, quality, semantic
from storage import Store
from workflows import Pipelines, valid_video

TEXT = '계란 2개를 프라이팬에 익혀요.'
RECIPE = {'title':'계란 요리','time':10,'ingredients':[{'raw_name':'계란','name':'계란','quantity':2,'unit':'개','evidence':TEXT}], 'steps':['계란을 익혀요.'],'tools':['프라이팬']}

class FakeLLM:
    """호출 수와 실패를 제어할 수 있는 결정적 Ollama 테스트 대역."""

    model='fake'; embedding_model='fake-embed'
    def __init__(self):
        """기본 응답, 호출 카운터와 임베딩 실패 스위치를 초기화한다."""
        self.calls=0; self.response=RECIPE; self.embed_fail=False
    def recipe(self,text,feedback=''):
        """입력과 무관하게 복제한 고정 레시피를 반환하고 호출 수를 증가시킨다."""
        self.calls+=1
        return copy.deepcopy(self.response)
    def embed(self,text):
        """고정 3차원 벡터를 반환하거나 설정에 따라 RuntimeError를 발생시킨다."""
        if self.embed_fail: raise RuntimeError('embedding unavailable')
        return [0.1,0.2,0.3]
    def tips(self,rows,pantry):
        """검색 입력과 무관하게 고정된 팁 문자열을 반환한다."""
        return '검증되지 않은 제안입니다.'

class FakeIndex:
    """메모리 사전으로 upsert·검색·실패를 흉내 내는 벡터 인덱스 대역."""

    backend='fake-index'
    def __init__(self):
        """빈 point 사전과 실패 스위치를 초기화한다."""
        self.rows={}; self.fail=False
    def upsert(self,row,vector):
        """행을 ID 기준으로 저장하거나 설정에 따라 실패한다."""
        if self.fail: raise RuntimeError('index unavailable')
        self.rows[row['id']]=row
    def search(self,query,filters):
        """저장된 모든 ID를 반환하거나 설정에 따라 실패한다."""
        if self.fail: raise RuntimeError('index unavailable')
        return list(self.rows)
    def health(self):
        """항상 준비됨과 현재 메모리 행 수를 반환한다."""
        return {'ready':True,'backend':self.backend,'vectors':len(self.rows)}
    def close(self):
        """외부 자원이 없으므로 아무 작업도 하지 않는다."""
        pass

class WorkflowTests(unittest.TestCase):
    """임시 SQLite와 대역 연동을 사용하는 두 LangGraph 단위 테스트."""

    def setUp(self):
        """각 테스트에 격리된 DB, 체크포인트와 대역 객체를 만든다."""
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.store=Store(self.root/'recipe.db'); self.llm=FakeLLM(); self.index=FakeIndex()
        self.graph=self.make_graph()
    def make_graph(self):
        """현재 테스트 객체의 의존성으로 새 Pipelines 인스턴스를 반환한다."""
        return Pipelines(self.store,self.llm,self.index,lambda url:(TEXT,'ko','fake'),str(self.root/'checkpoints.db'))
    def tearDown(self):
        """체크포인트 연결을 닫고 임시 폴더를 삭제한다."""
        self.graph.checkpoint_db.close(); self.temp.cleanup()
    def ingest(self,**payload):
        """새 UUID로 수집 그래프를 실행하고 저장된 작업 사전을 반환한다."""
        id=str(uuid.uuid4()); self.graph.run(id,payload or {'text':TEXT}); return self.store.job(id)
    def search(self,**req):
        """기본 달걀 pantry에 조건을 합쳐 검색하고 최종 결과 사전을 반환한다."""
        return self.graph.search.invoke({'request':{'pantry':['달걀'],**req}})['result']

    def test_schema_and_exact_aliases(self):
        """스키마와 정확한 별칭·근거 품질 규칙을 검증한다."""
        self.assertEqual(canonical(' 계란 '),'달걀')
        self.assertEqual(canonical('대파'),'대파')
        self.assertEqual(canonical('통마늘'),'통마늘')
        with self.assertRaises(ValueError): Recipe.model_validate({**RECIPE,'steps':[' ']})
        r=normalize(RECIPE); self.assertEqual(quality(r,TEXT),[])
        r['ingredients'][0]['name']='마늘'; self.assertTrue(quality(r,TEXT))

    def test_valid_urls(self):
        """허용된 YouTube URL과 위조·잘못된 URL 거부를 검증한다."""
        for url in ['https://youtu.be/UUOpe_sTKzA?si=x','https://www.youtube.com/watch?v=UUOpe_sTKzA&list=x','https://youtube.com/shorts/UUOpe_sTKzA']:
            self.assertEqual(valid_video(url),'UUOpe_sTKzA')
        for url in ['http://localhost/video','https://youtube.com.evil.com/watch?v=UUOpe_sTKzA','https://youtu.be/bad']:
            with self.assertRaises(ValueError):valid_video(url)

    def test_save_dedup_and_restart(self):
        """저장·중복 방지·DB 재연결 후 데이터 보존을 검증한다."""
        first=self.ingest(); self.assertEqual(first['status'],'complete',first)
        second=self.ingest(); self.assertTrue(second['result']['duplicate'])
        self.assertEqual(self.llm.calls,1)
        rows=Store(self.root/'recipe.db').all(); self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['transcript'],TEXT)
        self.assertEqual(rows[0]['index_status'],'indexed')
        self.assertEqual(rows[0]['recipe']['ingredients'][0]['raw_name'],'계란')
        self.assertEqual(rows[0]['recipe']['ingredients'][0]['name'],'달걀')

    def test_url_dedup_ignores_tracking(self):
        """추적 파라미터가 달라도 같은 영상으로 판정하는지 검증한다."""
        self.ingest(url='https://youtu.be/UUOpe_sTKzA?si=a')
        job=self.ingest(url='https://youtube.com/watch?v=UUOpe_sTKzA&list=b')
        self.assertEqual(job['status'],'complete',job)
        self.assertTrue(job['result']['duplicate'])

    def test_review_durable_and_bounded(self):
        """재검토 1회 제한과 재시작 후 사용자 확인 재개를 검증한다."""
        self.llm.response=copy.deepcopy(RECIPE);self.llm.response['ingredients'][0]['evidence']=''
        job=self.ingest(); self.assertEqual(job['status'],'review',job)
        self.assertEqual(self.llm.calls,2); self.assertEqual(self.store.all(),[])
        self.graph.checkpoint_db.close(); self.graph=self.make_graph()
        self.graph.run(job['id'],resume={'approved':True,'recipe':RECIPE})
        self.assertEqual(self.store.job(job['id'])['status'],'complete')
        self.assertEqual(self.llm.calls,2)
        self.assertEqual(self.store.all()[0]['semantic']['review_status'],'user_confirmed')

    def test_malformed_json_enters_review(self):
        """계속 잘못된 LLM 구조가 저장되지 않고 검토 상태인지 검증한다."""
        self.llm.response={'title':'invalid'}
        job=self.ingest(); self.assertEqual(job['status'],'review',job)
        self.assertEqual(self.llm.calls,2);self.assertEqual(self.store.all(),[])

    def test_index_failure_preserves_sql_and_reindex_is_idempotent(self):
        """인덱스 실패 시 원본 보존과 반복 재색인의 멱등성을 검증한다."""
        self.index.fail=True
        job=self.ingest();self.assertEqual(job['status'],'complete',job)
        r=job['result']['recipe'];self.assertEqual(r['index_status'],'failed')
        self.index.fail=False
        self.graph.reindex(r['id']);self.graph.reindex(r['id'])
        self.assertEqual(len(self.index.rows),1);self.assertEqual(len(self.store.all()),1)
        self.assertEqual(self.store.get(r['id'])['index_status'],'indexed')
        self.assertEqual(self.store.get(r['id'])['index_backend'],'fake-index')
        self.assertEqual(self.graph.reindex_all()['total'],0)

    def test_embedding_failure_is_not_recipe_loss(self):
        """임베딩 실패가 SQLite 레시피 손실로 이어지지 않는지 검증한다."""
        self.llm.embed_fail=True
        job=self.ingest();self.assertEqual(job['status'],'complete',job)
        self.assertEqual(job['result']['recipe']['index_status'],'failed')

    def test_recommendation_filters_and_fallback(self):
        """SQLite 폴백 추천과 모든 하드 필터 및 팁 생성을 검증한다."""
        self.ingest(); self.index.fail=True
        out=self.search();self.assertTrue(out['warnings'])
        self.assertEqual(out['recipes'][0]['coverage'],100)
        self.assertEqual(out['recipes'][0]['availability'],'수량 확인 필요')
        self.assertEqual(self.search(exclude_ingredients=['계란'])['recipes'],[])
        self.assertEqual(self.search(max_time=5)['recipes'],[])
        self.assertEqual(self.search(pantry=[],max_missing=0)['recipes'],[])
        self.assertEqual(self.search(tools=['냄비'])['recipes'],[])
        self.assertEqual(self.search(allergens=['우유'])['recipes'],[])
        self.assertEqual(self.search(min_spice=2)['recipes'],[])
        self.assertTrue(self.search(tips=True)['tips'])

    def test_semantic_unknown_is_not_zero(self):
        """맵기 미상은 None이고 청양고추 근거는 3인지 검증한다."""
        self.assertIsNone(semantic(normalize(RECIPE),TEXT)['spice_level'])
        r=copy.deepcopy(RECIPE);r['ingredients'][0]['name']='청양고추'
        self.assertEqual(semantic(normalize(r),TEXT)['spice_level'],3)

    def test_extract_failure_resume(self):
        """자막 추출 실패 작업을 같은 체크포인트에서 재개하는지 검증한다."""
        def fail(url):
            """입력 URL과 관계없이 네트워크 실패를 재현한다."""
            raise RuntimeError('network failed')
        self.graph.extract=fail
        job=self.ingest(url='https://youtu.be/UUOpe_sTKzA')
        self.assertEqual(job['status'],'failed')
        self.graph.extract=lambda url:(TEXT,'ko','fake')
        self.graph.run(job['id'])
        self.assertEqual(self.store.job(job['id'])['status'],'complete')

    def test_resume_before_first_checkpoint(self):
        """첫 체크포인트 전 종료된 작업도 저장 payload로 복구하는지 검증한다."""
        id=str(uuid.uuid4());self.store.job(id,status='queued',payload={'text':TEXT})
        self.graph.run(id)
        self.assertEqual(self.store.job(id)['status'],'complete')

if __name__=='__main__':unittest.main()
