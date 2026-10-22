"""원문 사실이 재검토·재시작·저장 경계를 넘어 유지되는지 검사한다."""
import copy
import tempfile
import unittest
import uuid
from pathlib import Path

from storage import Store
from workflows import Pipelines
from domain import normalize
from test_workflows import FakeIndex, FakeLLM
from test_step_quality import TEXT, FACTS, RECIPE


class StepLLM(FakeLLM):
    """서로 다른 사실·후보 응답으로 모델 경계만 대체한다."""

    def __init__(self):
        """기본 합성 응답과 독립 호출 기록을 준비한다."""
        super().__init__()
        self.response = copy.deepcopy(RECIPE)
        self.facts = copy.deepcopy(FACTS)
        self.source_calls = 0
        self.source_fail = False
        self.seen_facts = []

    def source_facts(self, transcript):
        """합성 사실을 복제해 반환하거나 수집 실패를 재현한다."""
        self.source_calls += 1
        if self.source_fail: raise RuntimeError('source extraction unavailable')
        return copy.deepcopy(self.facts)

    def recipe(self, transcript, feedback='', *, source_facts=None):
        """최초·재검토가 전달한 사실을 기록하고 고정 후보를 반환한다."""
        self.seen_facts.append(copy.deepcopy(source_facts))
        return super().recipe(transcript, feedback)


class StepWorkflowTests(unittest.TestCase):
    """사용자 DB 대신 테스트가 소유하는 임시 SQLite·체크포인트를 쓴다."""

    def setUp(self):
        """테스트 전용 저장소와 그래프를 준비한다."""
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name); self.store = Store(self.root / 'recipe.db')
        self.llm = StepLLM(); self.index = FakeIndex(); self.graph = self.make_graph()

    def make_graph(self):
        """동일 임시 체크포인트를 재연결할 수 있는 그래프를 반환한다."""
        return Pipelines(self.store, self.llm, self.index, lambda url: (TEXT, 'ko', 'fixture'), str(self.root / 'checkpoints.db'))

    def tearDown(self):
        """테스트 소유의 연결·임시 폴더만 정리한다."""
        self.graph.checkpoint_db.close(); self.temp.cleanup()

    def run_job(self):
        """합성 원문으로 새 작업을 실행해 최종 작업 행을 반환한다."""
        id = str(uuid.uuid4()); self.graph.run(id, {'text': TEXT})
        return self.store.job(id)

    def test_new_job_extracts_facts_before_structure_and_preserves_details(self):
        """원문 사실 1회와 구조화 1회로 근거를 함께 저장한다."""
        job = self.run_job()
        self.assertEqual(job['status'], 'complete', job)
        self.assertEqual(self.llm.source_calls, 1)
        self.assertTrue(self.llm.seen_facts[0])
        row = self.store.all()[0]
        self.assertEqual(row['recipe']['step_details'][1]['duration_seconds'], 90)
        self.assertIn('전자레인지', row['recipe']['steps'][1])
        self.assertEqual(row['transcript'], TEXT)

    def test_failed_repair_retains_facts_and_never_saves_before_review(self):
        """모델이 반복 누락해도 원문 사실은 고정되고 원본 행은 생성되지 않는다."""
        self.llm.response['step_details'][1]['tools'] = []
        job = self.run_job()
        self.assertEqual(job['status'], 'review', job)
        self.assertEqual(self.store.all(), [])
        self.assertEqual(self.llm.calls, 2)
        self.assertEqual(self.llm.source_calls, 1)
        self.assertEqual(self.llm.seen_facts[0], self.llm.seen_facts[1])
        self.assertTrue(job['result']['source_facts'])

    def test_source_failure_cannot_be_cleared_by_valid_recipe(self):
        """원문 사실 추출 실패는 후보 형식이 정상이어도 검토로 보낸다."""
        self.llm.source_fail = True
        job = self.run_job()
        self.assertEqual(job['status'], 'review', job)
        self.assertEqual(self.store.all(), [])
        self.assertEqual(self.llm.source_calls, 1)

    def test_review_survives_restart_and_preserves_user_prose(self):
        """재시작 후 명시적 승인만 저장하며 사용자 문장을 자동 교체하지 않는다."""
        self.llm.response['step_details'][1]['tools'] = []
        job = self.run_job(); self.assertEqual(job['status'], 'review', job)
        self.graph.checkpoint_db.close(); self.graph = self.make_graph()
        edited = copy.deepcopy(RECIPE); edited['steps'][0] = '사용자가 확인한 조리 문장'
        self.graph.run(job['id'], resume={'approved': True, 'recipe': edited})
        self.assertEqual(self.store.job(job['id'])['status'], 'complete')
        self.assertEqual(self.store.all()[0]['recipe']['steps'][0], edited['steps'][0])
        self.assertEqual(self.store.all()[0]['semantic']['review_status'], 'user_confirmed')
        self.assertEqual(self.llm.source_calls, 1)

    def test_old_checkpoint_already_at_persist_requires_review(self):
        """새 그래프 노드 이전 버전의 persist 진입도 자동 저장하지 않는다."""
        id = str(uuid.uuid4()); self.store.job(id, status='running')
        self.graph.ingest.update_state({'configurable': {'thread_id': id}},
            {'job_id': id, 'key': 'text:legacy', 'raw_transcript': TEXT,
             'transcript': TEXT, 'recipe': normalize(copy.deepcopy(RECIPE)), 'issues': []}, as_node='review')
        self.graph.run(id)
        self.assertEqual(self.store.job(id)['status'], 'review')
        self.assertEqual(self.store.all(), [])

    def test_changed_candidate_cannot_reuse_old_approval(self):
        """후보가 바뀌면 과거 승인 플래그만으로 저장할 수 없다."""
        id = str(uuid.uuid4()); self.store.job(id, status='running')
        self.graph.ingest.update_state({'configurable': {'thread_id': id}},
            {'job_id': id, 'key': 'text:changed', 'raw_transcript': TEXT,
             'transcript': TEXT, 'recipe': normalize(copy.deepcopy(RECIPE)), 'issues': [],
             'user_reviewed': True, 'approved_recipe_hash': 'not-this-candidate'}, as_node='review')
        self.graph.run(id)
        self.assertEqual(self.store.job(id)['status'], 'review')
        self.assertEqual(self.store.all(), [])
