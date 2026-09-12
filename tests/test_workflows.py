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
    model='fake'; embedding_model='fake-embed'
    def __init__(self): self.calls=0; self.response=RECIPE; self.embed_fail=False
    def recipe(self,text,feedback=''):
        self.calls+=1
        return copy.deepcopy(self.response)
    def embed(self,text):
        if self.embed_fail: raise RuntimeError('embedding unavailable')
        return [0.1,0.2,0.3]
    def tips(self,rows,pantry): return '검증되지 않은 제안입니다.'

class FakeIndex:
    def __init__(self): self.rows={}; self.fail=False
    def upsert(self,row,vector):
        if self.fail: raise RuntimeError('index unavailable')
        self.rows[row['id']]=row
    def search(self,query,filters):
        if self.fail: raise RuntimeError('index unavailable')
        return list(self.rows)

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.store=Store(self.root/'recipe.db'); self.llm=FakeLLM(); self.index=FakeIndex()
        self.graph=self.make_graph()
    def make_graph(self):
        return Pipelines(self.store,self.llm,self.index,lambda url:(TEXT,'ko','fake'),str(self.root/'checkpoints.db'))
    def tearDown(self): self.graph.checkpoint_db.close(); self.temp.cleanup()
    def ingest(self,**payload):
        id=str(uuid.uuid4()); self.graph.run(id,payload or {'text':TEXT}); return self.store.job(id)
    def search(self,**req): return self.graph.search.invoke({'request':{'pantry':['달걀'],**req}})['result']

    def test_schema_and_exact_aliases(self):
        self.assertEqual(canonical(' 계란 '),'달걀')
        self.assertEqual(canonical('대파'),'대파')
        self.assertEqual(canonical('통마늘'),'통마늘')
        with self.assertRaises(ValueError): Recipe.model_validate({**RECIPE,'steps':[' ']})
        r=normalize(RECIPE); self.assertEqual(quality(r,TEXT),[])
        r['ingredients'][0]['name']='마늘'; self.assertTrue(quality(r,TEXT))

    def test_valid_urls(self):
        for url in ['https://youtu.be/UUOpe_sTKzA?si=x','https://www.youtube.com/watch?v=UUOpe_sTKzA&list=x','https://youtube.com/shorts/UUOpe_sTKzA']:
            self.assertEqual(valid_video(url),'UUOpe_sTKzA')
        for url in ['http://localhost/video','https://youtube.com.evil.com/watch?v=UUOpe_sTKzA','https://youtu.be/bad']:
            with self.assertRaises(ValueError):valid_video(url)

    def test_save_dedup_and_restart(self):
        first=self.ingest(); self.assertEqual(first['status'],'complete',first)
        second=self.ingest(); self.assertTrue(second['result']['duplicate'])
        self.assertEqual(self.llm.calls,1)
        rows=Store(self.root/'recipe.db').all(); self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['transcript'],TEXT)
        self.assertEqual(rows[0]['index_status'],'indexed')
        self.assertEqual(rows[0]['recipe']['ingredients'][0]['raw_name'],'계란')
        self.assertEqual(rows[0]['recipe']['ingredients'][0]['name'],'달걀')

    def test_url_dedup_ignores_tracking(self):
        self.ingest(url='https://youtu.be/UUOpe_sTKzA?si=a')
        job=self.ingest(url='https://youtube.com/watch?v=UUOpe_sTKzA&list=b')
        self.assertEqual(job['status'],'complete',job)
        self.assertTrue(job['result']['duplicate'])

    def test_review_durable_and_bounded(self):
        self.llm.response=copy.deepcopy(RECIPE);self.llm.response['ingredients'][0]['evidence']=''
        job=self.ingest(); self.assertEqual(job['status'],'review',job)
        self.assertEqual(self.llm.calls,2); self.assertEqual(self.store.all(),[])
        self.graph.checkpoint_db.close(); self.graph=self.make_graph()
        self.graph.run(job['id'],resume={'approved':True,'recipe':RECIPE})
        self.assertEqual(self.store.job(job['id'])['status'],'complete')
        self.assertEqual(self.llm.calls,2)
        self.assertEqual(self.store.all()[0]['semantic']['review_status'],'user_confirmed')

    def test_malformed_json_enters_review(self):
        self.llm.response={'title':'invalid'}
        job=self.ingest(); self.assertEqual(job['status'],'review',job)
        self.assertEqual(self.llm.calls,2);self.assertEqual(self.store.all(),[])

    def test_index_failure_preserves_sql_and_reindex_is_idempotent(self):
        self.index.fail=True
        job=self.ingest();self.assertEqual(job['status'],'complete',job)
        r=job['result']['recipe'];self.assertEqual(r['index_status'],'failed')
        self.index.fail=False
        self.graph.reindex(r['id']);self.graph.reindex(r['id'])
        self.assertEqual(len(self.index.rows),1);self.assertEqual(len(self.store.all()),1)
        self.assertEqual(self.store.get(r['id'])['index_status'],'indexed')

    def test_embedding_failure_is_not_recipe_loss(self):
        self.llm.embed_fail=True
        job=self.ingest();self.assertEqual(job['status'],'complete',job)
        self.assertEqual(job['result']['recipe']['index_status'],'failed')

    def test_recommendation_filters_and_fallback(self):
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
        self.assertIsNone(semantic(normalize(RECIPE),TEXT)['spice_level'])
        r=copy.deepcopy(RECIPE);r['ingredients'][0]['name']='청양고추'
        self.assertEqual(semantic(normalize(r),TEXT)['spice_level'],3)

    def test_extract_failure_resume(self):
        def fail(url): raise RuntimeError('network failed')
        self.graph.extract=fail
        job=self.ingest(url='https://youtu.be/UUOpe_sTKzA')
        self.assertEqual(job['status'],'failed')
        self.graph.extract=lambda url:(TEXT,'ko','fake')
        self.graph.run(job['id'])
        self.assertEqual(self.store.job(job['id'])['status'],'complete')

    def test_resume_before_first_checkpoint(self):
        id=str(uuid.uuid4());self.store.job(id,status='queued',payload={'text':TEXT})
        self.graph.run(id)
        self.assertEqual(self.store.job(id)['status'],'complete')

if __name__=='__main__':unittest.main()
