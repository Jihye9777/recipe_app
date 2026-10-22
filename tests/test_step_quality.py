"""조리 사실과 최종 레시피의 누락·모순 회귀 검사."""
import copy
import unittest

import domain
from domain import Recipe, normalize, quality


SAUCE = '식초 1.5스푼을 그릇에 넣고 섞어요.'
EGG = '달걀 1개를 물에 넣고 전자레인지에서 1분 30초 익혀요.'
TEXT = SAUCE + '\n' + EGG


def ingredient(name, quantity, unit, evidence):
    """합성 원문의 재료 근거를 반환한다. 외부 자원을 사용하지 않는다."""
    return {'raw_name': name, 'name': name, 'quantity': quantity,
            'unit': unit, 'evidence': evidence}


INGREDIENTS = [ingredient('식초', 1.5, '스푼', SAUCE),
               ingredient('달걀', 1, '개', EGG), ingredient('물', None, None, EGG)]
DETAILS = [
    {'ingredients': [INGREDIENTS[0]], 'action': SAUCE, 'tools': ['그릇'],
     'duration_seconds': None, 'duration_text': None, 'evidence': SAUCE, 'source_step': 0},
    {'ingredients': INGREDIENTS[1:], 'action': EGG, 'tools': ['전자레인지'],
     'duration_seconds': 90, 'duration_text': '1분 30초', 'evidence': EGG, 'source_step': 1},
]
FACTS = {'ingredients': copy.deepcopy(INGREDIENTS), 'steps': copy.deepcopy(DETAILS)}
RECIPE = {'title': '합성 요리', 'ingredients': copy.deepcopy(INGREDIENTS),
          'steps': [SAUCE, EGG], 'step_details': copy.deepcopy(DETAILS),
          'tools': ['그릇', '전자레인지']}


class StepQualityTests(unittest.TestCase):
    """지원하는 표현을 검증하되 모호한 관계는 검토 사유로 남긴다."""

    def setUp(self):
        """구조화 필드가 없는 기존 구현은 동작 검사 전에 명확히 실패한다."""
        self.assertIn('step_details', Recipe.model_fields)

    def check(self, recipe=None, facts=None, text=TEXT):
        """실제 정규화·품질 검사를 합성 자료로 실행한다."""
        return quality(normalize(recipe or copy.deepcopy(RECIPE)), text,
                       source_facts=domain.SourceFacts.model_validate(facts or copy.deepcopy(FACTS)))

    def test_supported_recipe_keeps_quantity_tool_and_duration(self):
        """명시적 분량과 같은 단계의 기구·시간이 유지되면 통과한다."""
        self.assertEqual(self.check(), [])

    def test_omitted_or_changed_ingredient_requires_review(self):
        """식초 누락·수량 변경·단위 변경을 각각 검출한다."""
        for mutation in ('missing', 'quantity', 'unit'):
            with self.subTest(mutation=mutation):
                r = copy.deepcopy(RECIPE)
                if mutation == 'missing': r['ingredients'].pop(0)
                elif mutation == 'quantity': r['ingredients'][0]['quantity'] = 1
                else: r['ingredients'][0]['unit'] = '큰술'
                self.assertTrue(self.check(r))

    def test_step_tool_time_and_binding_cannot_be_dropped(self):
        """전체 tools에 기구가 있어도 단계 누락·시간 변경·단계 이동은 거부한다."""
        for mutation in ('tool', 'time', 'binding', 'prose'):
            with self.subTest(mutation=mutation):
                r = copy.deepcopy(RECIPE)
                if mutation == 'tool': r['step_details'][1]['tools'] = []
                elif mutation == 'time': r['step_details'][1]['duration_seconds'] = 60
                elif mutation == 'binding': r['step_details'][1]['source_step'] = 0
                else: r['steps'][1] = '물에 달걀 1개를 넣고 1분 30초 익혀요.'
                self.assertTrue(self.check(r))

    def test_unsupported_claim_inside_real_quote_is_rejected(self):
        """실제 인용문을 붙여도 원문에 없는 수량·도구는 통과하지 않는다."""
        r = copy.deepcopy(RECIPE)
        r['step_details'][1]['ingredients'][0]['quantity'] = 2
        r['step_details'][1]['tools'].append('오븐')
        self.assertTrue(self.check(r))

    def test_scanner_catches_omission_from_both_model_passes(self):
        """원문에 명시된 식초를 사실과 후보 모두 누락해도 검토한다."""
        r = copy.deepcopy(RECIPE); f = copy.deepcopy(FACTS)
        r['ingredients'].pop(0); f['ingredients'].pop(0)
        r['step_details'].pop(0); f['steps'].pop(0); r['steps'].pop(0)
        r['step_details'][0]['source_step'] = 0
        self.assertTrue(self.check(r, f))

    def test_fraction_and_seconds_equivalence(self):
        """단순 분수와 초 단위의 동등 표현을 안전하게 비교한다."""
        text = TEXT.replace('1.5스푼', '3/2스푼').replace('1분 30초', '90초')
        r = copy.deepcopy(RECIPE); f = copy.deepcopy(FACTS)
        for bundle in (r, f):
            for item in bundle['ingredients']: item['evidence'] = item['evidence'].replace('1.5스푼', '3/2스푼').replace('1분 30초', '90초')
            for step in bundle.get('step_details', bundle.get('steps')):
                for key in ('action', 'evidence'):
                    step[key] = step[key].replace('1.5스푼', '3/2스푼').replace('1분 30초', '90초')
                if step['duration_text']: step['duration_text'] = '90초'
                for item in step['ingredients']: item['evidence'] = item['evidence'].replace('1.5스푼', '3/2스푼').replace('1분 30초', '90초')
        r['steps'] = [s['action'] for s in r['step_details']]
        self.assertEqual(self.check(r, f, text), [])

    def test_literal_null_unit_is_normalized_without_guessing(self):
        """None 문자열은 실단위로 인정하지 않고 JSON null로 정규화한다."""
        r = copy.deepcopy(RECIPE); r['ingredients'][0]['unit'] = 'None'
        self.assertIsNone(normalize(r)['ingredients'][0]['unit'])
        self.assertTrue(self.check(r))

    def test_tasting_only_and_missing_details_require_review(self):
        """실질적 조리 정보가 없거나 신규 단계 구조가 없으면 검토한다."""
        r = copy.deepcopy(RECIPE); r['step_details'] = []; r['steps'] = ['맛있어요.']
        self.assertTrue(self.check(r))

    def test_partial_amount_is_not_assumed_to_be_total(self):
        """명확하지 않은 부분 사용량을 전체 분량으로 합산하지 않는다."""
        f = copy.deepcopy(FACTS); f['ingredients'][0]['amount_role'] = 'partial'
        self.assertTrue(self.check(facts=f))

    def test_free_prose_cannot_add_unsupported_ingredient_or_action(self):
        """별도 문장에 숨긴 재료·조리법 추가도 구조 정보로 우회하지 못한다."""
        r = copy.deepcopy(RECIPE); r['steps'][0] += ' 설탕을 넣고 볶아요.'
        self.assertTrue(self.check(r))

    def test_shortened_action_cannot_drop_unmodeled_conditions(self):
        """기구·시간 필드가 남아 있어도 원문 행위를 축약해 조건을 버리지 않는다."""
        r = copy.deepcopy(RECIPE); r['step_details'][1]['action'] = '달걀 1개를 물에 넣고'
        self.assertTrue(self.check(r))

    def test_grounded_step_use_does_not_replace_a_known_total(self):
        """단계 사용량은 원문과 같고 별도 전체량이 있으면 부분 표기만으로 실패하지 않는다."""
        r = copy.deepcopy(RECIPE); f = copy.deepcopy(FACTS)
        r['step_details'][0]['ingredients'][0]['amount_role'] = 'partial'
        f['steps'][0]['ingredients'][0]['amount_role'] = 'partial'
        self.assertEqual(self.check(r, f), [])
