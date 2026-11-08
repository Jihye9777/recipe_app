"""다중 출처의 교정·누락·저장 경계를 합성 자료로 검증한다."""
import copy
import tempfile
import unittest
import uuid
from pathlib import Path

from evidence import Source, SourceBundle, Correction, evidence_quality, effective_text
from storage import Store, public
from workflows import Pipelines
from test_step_workflow import StepLLM
from test_step_quality import TEXT, FACTS, RECIPE
from test_workflows import FakeIndex


class EvidenceTests(unittest.TestCase):
    """시각 근거가 없는 교정과 단계 누락을 자동 통과시키지 않는다."""

    def bundle(self):
        """음성 오타와 화면 표기가 다른 합성 출처 묶음을 반환한다."""
        return SourceBundle(video_id='Vpqv2Ux_IDM', sources=[
            Source(id='caption:0', kind='caption', text='우유 300mm 채다치지', start=1, end=3),
            Source(id='frame:0', kind='screen_text', text='우유 300ml 체다치즈', start=2, end=2),
        ], warnings=['간격별 화면만 확인했습니다'])

    def test_correction_requires_screen_quote_and_preserves_original(self):
        """증거가 있는 오타 교정만 허용하고 원래 자막은 보존한다."""
        bundle = self.bundle()
        bundle.corrections = [Correction(source_id='caption:0', original='300mm',
            target_source_id='frame:0', corrected='300ml')]
        self.assertNotIn('300mm', effective_text(bundle))
        self.assertIn('300ml', effective_text(bundle))
        self.assertIn('300mm', bundle.sources[0].text)
        bundle.corrections[0].corrected = '500ml'
        with self.assertRaises(ValueError):
            effective_text(bundle)

    def test_visual_source_must_have_real_time_and_unique_id(self):
        """음수·역전 시점, 중복 ID, 시점 없는 화면 출처를 거부한다."""
        for args in [dict(start=-1, end=2), dict(start=3, end=2), dict(start=None, end=None)]:
            with self.assertRaises(ValueError):
                Source(id='frame:0', kind='screen_text', text='마늘 볶기', **args)
        with self.assertRaises(ValueError):
            SourceBundle(sources=[Source(id='x', kind='description', text='a'),
                                  Source(id='x', kind='description', text='b')])

    def test_missing_garlic_action_and_noodle_time_are_reviewed(self):
        """고정 사실에서 빠뜨린 화면 동작과 시간도 출처에서 독립 검사한다."""
        bundle = SourceBundle(sources=[Source(id='frame:0', kind='screen_text',
            text='마늘을 팬에 가열해요. 당면을 6분 삶아요.', start=3, end=3)])
        issues = evidence_quality(copy.deepcopy(RECIPE), copy.deepcopy(FACTS), bundle)
        self.assertTrue(any('동작' in issue for issue in issues), issues)
        self.assertTrue(any('시간' in issue for issue in issues), issues)

    def test_unreferenced_or_invented_source_cannot_support_claim(self):
        """유효 인용 문구가 있어도 허위 출처 ID를 사용하면 검토한다."""
        recipe = copy.deepcopy(RECIPE)
        recipe['ingredients'][0]['source_ids'] = ['invented']
        bundle = SourceBundle(sources=[Source(id='caption:0', kind='caption', text=TEXT, start=0, end=8)])
        self.assertTrue(any('출처' in issue for issue in evidence_quality(recipe, FACTS, bundle)))

    def test_length_unit_is_reviewed_without_guessing_millilitres(self):
        """우유 300mm를 원문대로 두되 분량 단위 문제로 검토한다."""
        from recipe_quality import _check_item
        item = {'raw_name':'우유', 'name':'우유', 'quantity':300, 'unit':'mm', 'evidence':'우유 300mm'}
        self.assertTrue(any('길이 단위' in issue for issue in _check_item(item, '우유 300mm')))
        self.assertEqual(item['unit'], 'mm')


class EvidenceWorkflowTests(unittest.TestCase):
    """재분석은 기존 행을 보존하고 불완전한 사용자 승인도 초안으로 저장한다."""

    def setUp(self):
        """격리 저장소와 합성 수집기를 구성한다."""
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'recipe.db')
        self.llm = StepLLM()
        self.graph = Pipelines(self.store, self.llm, FakeIndex(), lambda url: (TEXT, 'ko', 'fake'),
                               str(self.root / 'checkpoints.db'))

    def tearDown(self):
        """테스트 소유 임시 자원만 정리한다."""
        self.graph.checkpoint_db.close()
        self.temp.cleanup()

    def test_reanalysis_creates_candidate_without_changing_original(self):
        """같은 URL의 명시적 재분석은 새로운 원본·작업 관계를 만든다."""
        first = str(uuid.uuid4())
        self.graph.run(first, {'url': 'https://youtu.be/gcwOptvjdgA'})
        original = self.store.all()[0]
        next_job = str(uuid.uuid4())
        self.graph.run(next_job, {'url': original['source_url'], 'reanalyze_of': original['id']})
        self.assertEqual(len(self.store.all()), 2)
        self.assertEqual(self.store.get(original['id']), original)
        candidates = [row for row in self.store.all() if row['id'] != original['id']]
        self.assertEqual(candidates[0]['semantic']['reanalyze_of'], original['id'])

    def test_incomplete_user_confirmed_recipe_stays_draft(self):
        """저장 승인은 남아 있는 누락을 정확한 레시피로 바꾸지 않는다."""
        self.llm.response['step_details'][1]['tools'] = []
        job_id = str(uuid.uuid4())
        self.graph.run(job_id, {'text': TEXT})
        self.graph.run(job_id, resume={'approved': True})
        row = self.store.all()[0]
        self.assertEqual(public(row)['quality_status'], 'draft')
        self.assertTrue(row['semantic']['quality_issues'])

    def test_legacy_rows_are_unverified_without_rewrite(self):
        """기존 JSON은 그대로 읽고 UI에서 검증 상태를 새로 지어내지 않는다."""
        row = self.store.save('legacy', 'legacy:test', '', TEXT, RECIPE, {}, 'old')
        self.assertEqual(public(row)['quality_status'], 'unverified')
        self.assertEqual(Store(self.root / 'recipe.db').get('legacy')['recipe'], RECIPE)

    def test_multisource_review_preserves_sources_and_snapshot_approval(self):
        """화면 교정 자료·출처 ID를 검토 재개와 원본 저장 사이에 보존한다."""
        from unittest.mock import Mock
        text = '우유 300ml를 넣어요'
        ingredient = {'raw_name':'우유', 'name':'우유', 'quantity':300, 'unit':'ml',
                      'evidence':'우유 300ml', 'source_ids':['frame:0']}
        step = {'ingredients':[{**ingredient, 'amount_role':'total'}], 'action':text, 'tools':[],
                'duration_seconds':None, 'duration_text':None, 'heat':None,
                'evidence':text, 'source_step':0, 'source_ids':['frame:0']}
        recipe = {'title':'합성', 'ingredients':[ingredient], 'steps':[text + '.'], 'step_details':[step]}
        facts = {'ingredients':[{**ingredient, 'amount_role':'total'}], 'steps':[step]}
        facts = copy.deepcopy(facts)
        facts['steps'][0]['tools'] = [' ']
        bundle = SourceBundle(video_id='Vpqv2Ux_IDM', sources=[
            Source(id='caption:0', kind='caption', text='우유 300mm', start=1, end=2),
            Source(id='frame:0', kind='screen_text', text=text, start=1, end=1)],
            warnings=['화면 판독은 확인이 필요합니다'])
        collector = Mock()
        collector.collect.return_value = bundle
        self.graph.collector = collector
        self.llm.evidence_facts = Mock(return_value={'facts':facts, 'corrections':[
            {'source_id':'caption:0', 'original':'300mm', 'target_source_id':'frame:0', 'corrected':'300ml'}]})
        self.llm.response = recipe
        self.llm.recipe = Mock(side_effect=TimeoutError('불필요한 두 번째 모델 호출'))
        job_id = str(uuid.uuid4())
        self.graph.run(job_id, {'url':'https://youtu.be/Vpqv2Ux_IDM'})
        job = self.store.job(job_id)
        self.assertEqual(job['status'], 'review', job)
        self.llm.recipe.assert_not_called()
        self.assertEqual(job['result']['recipe']['tools'], [])
        self.assertTrue(any('기구' in issue for issue in job['result']['issues']))
        self.assertEqual(job['result']['sources']['corrections'][0]['corrected'], '300ml')
        self.graph.run(job_id, resume={'approved':True})
        row = self.store.all()[0]
        self.assertEqual(row['sources']['sources'][0]['text'], '우유 300mm')
        self.assertEqual(row['recipe']['ingredients'][0]['unit'], 'ml')
        self.assertEqual(public(row)['quality_status'], 'draft')
        self.assertNotEqual(self.graph.recipe_hash(row['recipe'], row['sources']),
                            self.graph.recipe_hash(row['recipe'], {**row['sources'], 'revision':2}))
