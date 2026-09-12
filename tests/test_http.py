import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from test_workflows import FakeLLM, FakeIndex, TEXT, RECIPE
from storage import Store
from workflows import Pipelines

class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(); cls.root=Path(cls.temp.name)
        os.environ['RECIPE_DATA_DIR']=str(cls.root)
        import server
        cls.server=server
        cls.llm=FakeLLM(); cls.index=FakeIndex()
        server.STORE=Store(cls.root/'recipe.db')
        server.PIPELINES=Pipelines(server.STORE,cls.llm,cls.index,lambda url:(TEXT,'ko','fake'),str(cls.root/'checkpoints.db'))
        cls.httpd=ThreadingHTTPServer(('127.0.0.1',0),server.RecipeHandler)
        cls.thread=threading.Thread(target=cls.httpd.serve_forever,daemon=True); cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.httpd.server_port)
        cls.client=build_opener(ProxyHandler({}))
    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown();cls.httpd.server_close();cls.thread.join()
        cls.server.WORKER.shutdown(wait=True);cls.server.PIPELINES.checkpoint_db.close()
        cls.temp.cleanup();os.environ.pop('RECIPE_DATA_DIR',None)
    def request(self,path,body=None):
        req=Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        try:
            with self.client.open(req,timeout=10) as response:
                return response.status,json.loads(response.read())
        except HTTPError as error:
            return error.code,error.read().decode()
    def job(self,id):
        for _ in range(100):
            _,job=self.request('/api/jobs/'+id)
            if job['status'] in {'complete','review','failed'}:return job
            time.sleep(0.02)
        self.fail('Job did not finish')
    def test_async_save_search_and_detail(self):
        code,out=self.request('/api/analyze',{'text':TEXT});self.assertEqual(code,202)
        job=self.job(out['job_id']);self.assertEqual(job['status'],'complete',job)
        _,rows=self.request('/api/recipes');self.assertTrue(rows['recipes'])
        code,out=self.request('/api/pantry',{'pantry':['계란','달걀']});self.assertEqual(out['pantry'],['달걀'])
        code,out=self.request('/api/search',{'pantry':['계란'],'max_missing':0});self.assertEqual(code,200)
        self.assertEqual(out['recipes'][0]['coverage'],100)
        self.assertEqual(self.request('/api/reindex',{'id':rows['recipes'][0]['id']})[0],200)
    def test_private_files_not_served(self):
        for path in ['/server.py','/data/recipe.db','/data/checkpoints.db','/.runtime/audio.mp4','/../server.py','/%73erver.py']:
            self.assertEqual(self.request(path)[0],404,path)
    def test_errors_are_json(self):
        code,out=self.request('/api/search',{'max_missing':-1})
        self.assertEqual(code,422);self.assertIn('error',json.loads(out))
        self.assertEqual(self.request('/api/jobs/not-found')[0],404)
    def test_health_checks_components(self):
        with patch('health.requests.get') as get, patch('health.create_connection'):
            get.return_value.json.return_value={'models':[{'name':'gemma4:latest'},{'name':'embeddinggemma:latest'}]}
            code,out=self.request('/api/health')
            self.assertEqual(code,200);self.assertTrue(out['ready'])
    def test_legacy_import_is_idempotent(self):
        old={'id':'old-test','title':'예전 레시피','ingredients':['감자'],'steps':['익혀요.'],'time':5}
        self.assertEqual(self.request('/api/import',{'recipes':[old]})[0],200)
        self.request('/api/import',{'recipes':[old]})
        rows=self.server.STORE.all()
        self.assertEqual(len([r for r in rows if r['source_key']=='legacy:old-test']),1)

    def test_review_rejects_invalid_edit_without_losing_pause(self):
        import copy
        self.llm.response=copy.deepcopy(RECIPE)
        self.llm.response['ingredients'][0]['evidence']=''
        try:
            _,out=self.request('/api/analyze',{'text':TEXT+' 확인 테스트.'})
            id=out['job_id'];self.assertEqual(self.job(id)['status'],'review')
            code,_=self.request('/api/review',{'job_id':id,'approved':True,'recipe':{'title':'잘못된 구조'}})
            self.assertEqual(code,422)
            self.assertEqual(self.request('/api/jobs/'+id)[1]['status'],'review')
            code,_=self.request('/api/review',{'job_id':id,'approved':True,'recipe':RECIPE})
            self.assertEqual(code,202);self.assertEqual(self.job(id)['status'],'complete')
        finally:self.llm.response=RECIPE

    def test_transcript_fallback_branch(self):
        with patch.object(self.server,'transcript_from_youtube_transcript_api',side_effect=RuntimeError('no captions')), patch.object(self.server,'transcript_from_local_whisper',return_value=(TEXT,'ko','whisper')) as whisper:
            result=self.server.extract_transcript('https://youtu.be/UUOpe_sTKzA')
            self.assertEqual(result[0],TEXT);whisper.assert_called_once()

if __name__=='__main__':unittest.main()
