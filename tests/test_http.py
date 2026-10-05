"""한입노트 HTTP API의 격리된 통합 테스트."""

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
    """임시 DB와 외부 연동 대역을 사용하는 실제 HTTP 라우팅 테스트."""

    @classmethod
    def setUpClass(cls):
        """임시 Store, 가짜 AI·인덱스와 임의 포트 테스트 서버를 시작한다."""
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
        """HTTP 서버·작업자·체크포인트 연결과 임시 폴더를 정리한다."""
        cls.httpd.shutdown();cls.httpd.server_close();cls.thread.join()
        cls.server.WORKER.shutdown(wait=True);cls.server.PIPELINES.checkpoint_db.close()
        cls.temp.cleanup();os.environ.pop('RECIPE_DATA_DIR',None)
    def request(self,path,body=None):
        """테스트 서버에 GET 또는 JSON POST 요청을 보내 상태와 본문을 반환한다.

        Args:
            path: 슬래시로 시작하는 API 또는 정적 파일 경로.
            body: POST JSON 사전. ``None``이면 GET 요청을 보낸다.

        Returns:
            성공 시 ``(HTTP 상태, 역직렬화 JSON)``. HTTP 오류 응답이면
            ``(오류 상태, 원문 문자열)`` 튜플.
        """
        req=Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        try:
            with self.client.open(req,timeout=10) as response:
                return response.status,json.loads(response.read())
        except HTTPError as error:
            return error.code,error.read().decode()
    def job(self,id):
        """작업이 종료 상태에 도달할 때까지 조회하고 최종 작업 사전을 반환한다."""
        for _ in range(100):
            _,job=self.request('/api/jobs/'+id)
            if job['status'] in {'complete','review','failed'}:return job
            time.sleep(0.02)
        self.fail('Job did not finish')
    def test_async_save_search_and_detail(self):
        """비동기 저장부터 조회·검색·개별/전체 재색인까지 검증한다."""
        code,out=self.request('/api/analyze',{'text':TEXT});self.assertEqual(code,202)
        job=self.job(out['job_id']);self.assertEqual(job['status'],'complete',job)
        _,rows=self.request('/api/recipes');self.assertTrue(rows['recipes'])
        code,out=self.request('/api/pantry',{'pantry':['계란','달걀']});self.assertEqual(out['pantry'],['달걀'])
        code,out=self.request('/api/search',{'pantry':['계란'],'max_missing':0});self.assertEqual(code,200)
        self.assertEqual(out['recipes'][0]['coverage'],100)
        self.assertEqual(self.request('/api/reindex',{'id':rows['recipes'][0]['id']})[0],200)
        code,out=self.request('/api/reindex-all',{})
        self.assertEqual(code,200);self.assertEqual(out['failed'],0)
    def test_private_files_not_served(self):
        """소스·DB·체크포인트·임시 파일 경로가 모두 404인지 검증한다."""
        for path in ['/server.py','/data/recipe.db','/data/checkpoints.db','/.runtime/audio.mp4','/../server.py','/%73erver.py']:
            self.assertEqual(self.request(path)[0],404,path)
    def test_errors_are_json(self):
        """잘못된 검색과 없는 작업이 구조화된 오류를 반환하는지 검증한다."""
        code,out=self.request('/api/search',{'max_missing':-1})
        self.assertEqual(code,422);self.assertIn('error',json.loads(out))
        self.assertEqual(self.request('/api/jobs/not-found')[0],404)
    def test_health_checks_components(self):
        """준비된 대역 구성에서 통합 health 상태가 true인지 검증한다."""
        with patch('health.requests.get') as get:
            get.return_value.json.return_value={'models':[{'name':'gemma4:latest'},{'name':'embeddinggemma:latest'}]}
            code,out=self.request('/api/health')
            self.assertEqual(code,200);self.assertTrue(out['ready'])
    def test_legacy_import_is_idempotent(self):
        """동일한 과거 브라우저 레시피를 반복 이관해도 한 건인지 검증한다."""
        old={'id':'old-test','title':'예전 레시피','ingredients':['감자'],'steps':['익혀요.'],'time':5}
        self.assertEqual(self.request('/api/import',{'recipes':[old]})[0],200)
        self.request('/api/import',{'recipes':[old]})
        rows=self.server.STORE.all()
        self.assertEqual(len([r for r in rows if r['source_key']=='legacy:old-test']),1)

    def test_review_rejects_invalid_edit_without_losing_pause(self):
        """잘못된 검토 수정은 거부하고 올바른 승인으로 재개되는지 검증한다."""
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
        """자막 API 실패 시 로컬 Whisper 함수가 호출되는지 검증한다."""
        with patch.object(self.server,'transcript_from_youtube_transcript_api',side_effect=RuntimeError('no captions')), patch.object(self.server,'transcript_from_local_whisper',return_value=(TEXT,'ko','whisper')) as whisper:
            result=self.server.extract_transcript('https://youtu.be/UUOpe_sTKzA')
            self.assertEqual(result[0],TEXT);whisper.assert_called_once()

if __name__=='__main__':unittest.main()
