"""한입노트 HTTP API의 격리된 통합 테스트."""

import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from fastapi.testclient import TestClient
from test_workflows import FakeLLM, FakeIndex, TEXT, RECIPE
from storage import Store
from workflows import Pipelines

class HTTPTests(unittest.TestCase):
    """임시 DB와 외부 연동 대역을 사용하는 FastAPI HTTP 경계 테스트."""

    @classmethod
    def setUpClass(cls):
        """임시 Store·가짜 연동으로 ASGI 수명을 시작한다. 사용자 DB는 사용하지 않는다."""
        cls.temp=tempfile.TemporaryDirectory(); cls.root=Path(cls.temp.name)
        cls.old_tempdir = tempfile.tempdir
        cls.environment = patch.dict(os.environ, {
            'RECIPE_DATA_DIR': str(cls.root), 'RECIPE_RUNTIME_DIR': str(cls.root),
        })
        cls.environment.start()
        import server
        cls.server=server
        cls.llm=FakeLLM(); cls.index=FakeIndex()
        server.STORE=Store(cls.root/'recipe.db')
        server.PIPELINES=Pipelines(server.STORE,cls.llm,cls.index,lambda url:(TEXT,'ko','fake'),str(cls.root/'checkpoints.db'))
        cls.client = TestClient(server.app, raise_server_exceptions=False)
        cls.client.__enter__()
    @classmethod
    def tearDownClass(cls):
        """lifespan에서 연결을 닫고 이 테스트가 만든 임시 폴더만 자동 삭제한다."""
        cls.client.__exit__(None, None, None)
        tempfile.tempdir = cls.old_tempdir
        cls.environment.stop()
        cls.temp.cleanup()
    def request(self,path,body=None):
        """테스트 서버에 GET 또는 JSON POST 요청을 보내 상태와 본문을 반환한다.

        Args:
            path: 슬래시로 시작하는 API 또는 정적 파일 경로.
            body: POST JSON 사전. ``None``이면 GET 요청을 보낸다.

        Returns:
            성공 시 ``(HTTP 상태, 역직렬화 JSON)``. HTTP 오류 응답이면
            ``(오류 상태, 원문 문자열)`` 튜플.
        """
        response = self.client.get(path) if body is None else self.client.post(path, json=body)
        return response.status_code, response.json() if response.is_success else response.text
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

    def test_delete_recipe_contract_and_data_isolation(self):
        """DELETE 경로의 정상·없는 UUID·잘못된 ID와 나머지 원본 보존을 검증한다."""
        _,accepted=self.request('/api/analyze',{'text':TEXT+' 삭제 API 테스트.'})
        id=self.job(accepted['job_id'])['result']['recipe']['id']
        before=[row for row in self.server.STORE.all() if row['id']!=id]
        pantry=self.server.STORE.pantry()
        response=self.client.delete('/api/recipes/'+id)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json(),{'id':id,'deleted':True})
        self.assertEqual(self.server.STORE.all(),before)
        self.assertNotIn(id,self.index.rows)
        self.assertEqual(self.server.STORE.pantry(),pantry)
        self.assertEqual(self.client.delete('/api/recipes/'+id).status_code,404)
        self.assertEqual(self.client.delete('/api/recipes/not-a-uuid').status_code,422)
        schema=self.client.get('/openapi.json').json()
        self.assertIn('delete',schema['paths']['/api/recipes/{recipe_id}'])

    def test_delete_failure_keeps_recipe_available_for_retry(self):
        """인덱스 삭제 오류는 오류 JSON으로 알리고 저장 원본을 보존한다."""
        _,accepted=self.request('/api/analyze',{'text':TEXT+' 삭제 실패 테스트.'})
        id=self.job(accepted['job_id'])['result']['recipe']['id']
        self.index.fail=True
        try:
            response=self.client.delete('/api/recipes/'+id)
            self.assertEqual(response.status_code,422,response.text)
            self.assertIn('error',response.json())
            self.assertIsNotNone(self.server.STORE.get(id))
        finally:
            self.index.fail=False

    def test_approved_logo_is_public_but_other_assets_are_private(self):
        """승인된 로고 PNG만 공개하며 임의의 asset 경로는 허용하지 않는다."""
        response = self.client.get('/assets/cook-diary-rabbit.png')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'image/png')
        self.assertTrue(response.content.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual(self.client.get('/assets/unapproved.png').status_code, 404)

    def test_korean_font_url_serves_ttf_without_exposing_other_files(self):
        """한글·공백 파일명의 웹폰트를 제공하며 다른 글꼴 경로는 공개하지 않는다."""
        response = self.client.get('/assets/fonts/나눔손글씨 무궁화.ttf')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'font/ttf')
        self.assertTrue(response.content.startswith(b'\x00\x01\x00\x00'))
        self.assertEqual(self.client.get('/assets/fonts/unapproved.ttf').status_code, 404)

    def test_openapi_describes_requests_and_job_responses(self):
        """문서에 분석·검색 입력과 202 작업 응답 스키마가 공개되는지 검증한다."""
        code, schema = self.request('/openapi.json')
        self.assertEqual(code, 200)
        paths = schema['paths']
        for path in ['/api/analyze', '/api/search', '/api/review', '/api/retry',
                     '/api/pantry', '/api/reindex', '/api/reindex-all']:
            self.assertIn('requestBody', paths[path]['post'], path)
        analyze = paths['/api/analyze']['post']
        self.assertIn('202', analyze['responses'])
        self.assertIn('schema', analyze['responses']['202']['content']['application/json'])
        search = schema['components']['schemas']['SearchInput']
        self.assertIn('pantry', search['properties'])
        self.assertIn('max_missing', search['properties'])

    def test_docs_and_existing_frontend_are_available(self):
        """Swagger UI와 기존 홈페이지가 함께 제공되는지 검증한다."""
        for path, marker in [('/docs', 'swagger-ui'), ('/redoc', 'redoc'), ('/', '<html')]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(marker, response.text.lower())

    def test_body_contract_rejects_invalid_requests_as_json(self):
        """JSON 객체·크기·Content-Type 계약과 누락 필드를 검증한다."""
        for content in ['[]', '{', '', '{"text":"' + 'x' * 2_000_000 + '"}']:
            response = self.client.post('/api/analyze', content=content,
                                        headers={'Content-Type': 'application/json'})
            self.assertEqual(response.status_code, 422)
            self.assertIn('error', response.json())
        response = self.client.post('/api/analyze', content='text')
        self.assertEqual(response.status_code, 415)
        self.assertIn('error', response.json())
        for path in ['/api/retry', '/api/review', '/api/reindex']:
            response = self.client.post(path, json={})
            self.assertEqual(response.status_code, 422)
            self.assertIn('error', response.json())

    def test_unexpected_failure_returns_json(self):
        """예상치 못한 저장소 오류도 빈 응답 대신 500 오류 JSON인지 검증한다."""
        with patch.object(self.server.STORE, 'all', side_effect=Exception('test failure')):
            response = self.client.get('/api/recipes')
        self.assertEqual(response.status_code, 500)
        self.assertIn('error', response.json())
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
    def test_legacy_import_is_unavailable_without_changing_saved_recipes(self):
        """제거된 이관 요청은 거부하고 저장된 레시피를 변경하지 않는다."""
        old={'id':'old-test','title':'예전 레시피','ingredients':['감자'],'steps':['익혀요.'],'time':5}
        before = self.server.STORE.all()
        self.assertIn(self.request('/api/import',{'recipes':[old]})[0], (404, 405))
        self.assertEqual(self.server.STORE.all(), before)
        self.assertNotIn('/api/import', self.client.get('/openapi.json').json()['paths'])

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

class LifespanTests(unittest.TestCase):
    """서버 재시작 시 실제 Qdrant 파일 잠금과 체크포인트 종료를 검증한다."""

    def test_shutdown_releases_qdrant_and_allows_restart(self):
        """같은 인덱스 경로로 앱을 두 번 시작할 수 있어야 한다."""
        import sqlite3
        import server

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(server, 'DATA_DIR', root), patch.object(server, 'RUNTIME_DIR', root), \
                 patch.object(server, 'Ollama', FakeLLM), \
                 patch.dict(os.environ, {'QDRANT_PATH': str(root / 'qdrant')}):
                for _ in range(2):
                    with TestClient(server.app) as client:
                        self.assertEqual(client.get('/docs').status_code, 200)
                        graph = server.pipelines()
                        self.assertTrue(graph.index.health()['ready'])
                    with self.assertRaises(sqlite3.ProgrammingError):
                        graph.checkpoint_db.execute('SELECT 1')
                    self.assertIsNone(server.WORKER)
                    self.assertIsNone(server.PIPELINES)

    def test_uvicorn_serves_docs_over_real_http(self):
        """임시 포트의 실제 Uvicorn에서 웹 화면·문서·API 명세를 검증한다."""
        import socket
        import threading
        import uvicorn
        from urllib.request import build_opener, ProxyHandler
        import server

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(server, 'DATA_DIR', root), patch.object(server, 'RUNTIME_DIR', root):
                listener = socket.socket()
                listener.bind(('127.0.0.1', 0))
                base = 'http://127.0.0.1:' + str(listener.getsockname()[1])
                runner = uvicorn.Server(uvicorn.Config(server.app, log_level='error'))
                thread = threading.Thread(target=runner.run, kwargs={'sockets': [listener]}, daemon=True)
                thread.start()
                try:
                    deadline = time.monotonic() + 10
                    while not runner.started and thread.is_alive() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(runner.started, 'Uvicorn startup failed')
                    client = build_opener(ProxyHandler({}))
                    for path, marker in [('/', '<html'), ('/docs', 'swagger-ui')]:
                        with client.open(base + path, timeout=5) as response:
                            self.assertEqual(response.status, 200)
                            self.assertIn(marker, response.read().decode().lower())
                    with client.open(base + '/openapi.json', timeout=5) as response:
                        self.assertIn('/api/analyze', json.loads(response.read())['paths'])
                finally:
                    runner.should_exit = True
                    thread.join(timeout=10)
                    listener.close()
                self.assertFalse(thread.is_alive(), 'Uvicorn shutdown failed')


if __name__=='__main__':unittest.main()
