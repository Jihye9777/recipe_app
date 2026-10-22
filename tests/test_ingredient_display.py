"""미상 재료 값의 공개 표시를 원본 변경 없이 검증한다."""

import copy
import unittest

from storage import public


class IngredientDisplayTests(unittest.TestCase):
    """실제 API 변환 함수가 사용자용 문자열을 만드는 결과를 검사한다."""

    def test_unknown_values_have_one_korean_marker_without_guessing(self):
        """null과 과거 문자열 None 모두 확인 어려움으로 표시하고 수치는 유지한다."""
        cases = [
            ({'name': '식초', 'quantity': 1.5, 'unit': 'None'}, '식초 1.5 (확인 어려움)'),
            ({'name': '식초', 'quantity': 1.5, 'unit': None}, '식초 1.5 (확인 어려움)'),
            ({'name': '깨', 'quantity': None, 'unit': 'None'}, '깨 (확인 어려움)'),
            ({'name': '깨', 'quantity': 'None', 'unit': ' null '}, '깨 (확인 어려움)'),
            ({'name': '참기름', 'quantity': 0.5, 'unit': '스푼'}, '참기름 0.5 스푼'),
            ({'name': '물', 'quantity': None, 'unit': ''}, '물 (확인 어려움)'),
        ]
        for ingredient, expected in cases:
            with self.subTest(ingredient=ingredient):
                row = {'id': 'fixture', 'source_url': '', 'semantic': {},
                       'index_status': 'indexed', 'recipe': {'title': '테스트',
                       'ingredients': [ingredient], 'steps': ['섞어요.']}}
                original = copy.deepcopy(row)
                result = public(row)
                self.assertEqual(result['ingredients'], [expected])
                self.assertEqual(result['ingredient_details'], [ingredient])
                self.assertEqual(row, original)
