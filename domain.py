"""Recipe schemas and conservative, versioned semantic enrichment."""
import re
import unicodedata
from pydantic import BaseModel, ConfigDict, Field, field_validator

class Ingredient(BaseModel):
    """구조화된 재료 한 항목의 입력·저장 스키마.

    Attributes:
        raw_name: 자막에 등장한 원래 재료명.
        name: 별칭 규칙을 적용한 표준 재료명.
        quantity: 0보다 큰 수량. 원문에 없으면 ``None``.
        unit: 개, g, 큰술 등의 단위. 알 수 없으면 ``None``.
        optional: 없어도 되는 선택 재료인지 여부.
        evidence: 이 재료를 추출한 근거가 되는 원문 구절.
    """
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, allow_inf_nan=False)
    raw_name: str = Field(min_length=1)
    name: str = Field(min_length=1)
    quantity: float | None = Field(default=None, gt=0)
    unit: str | None = None
    optional: bool = False
    evidence: str = ''

class Recipe(BaseModel):
    """LLM 출력과 SQLite 저장에 공통으로 사용하는 레시피 스키마.

    Attributes:
        title: 비어 있지 않은 레시피 제목.
        category: 음식 분류. 기본값은 ``요리``.
        time: 명시된 전체 조리 시간(분). 모르면 ``None``.
        servings: 명시된 인분 수. 모르면 ``None``.
        ingredients: 하나 이상의 :class:`Ingredient` 목록.
        steps: 순서가 보존된 조리 단계 목록.
        tools: 원문에서 확인된 조리 도구 목록.
    """
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1)
    category: str = '요리'
    time: int | None = Field(default=None, ge=1)
    servings: int | None = Field(default=None, ge=1)
    ingredients: list[Ingredient] = Field(min_length=1)
    steps: list[str] = Field(min_length=1)
    tools: list[str] = Field(default_factory=list)

    @field_validator('steps', 'tools')
    @classmethod
    def nonempty_items(cls, values):
        """조리 단계와 도구 목록의 빈 문자열을 거부하고 공백을 정리한다.

        Args:
            values: Pydantic이 전달한 문자열 목록.

        Returns:
            각 항목의 앞뒤 공백을 제거한 새 문자열 목록.

        Raises:
            ValueError: 목록 안에 빈 문자열 또는 공백뿐인 항목이 있을 때.
        """
        if any(not x.strip() for x in values): raise ValueError('빈 조리 단계/도구는 사용할 수 없습니다.')
        return [x.strip() for x in values]

ALIASES = {'계란': '달걀', '고추가루': '고춧가루', '올리브오일': '올리브유'}
UNITS = {'스푼': None, '큰술': '큰술', '작은술': '작은술', '그램': 'g', '킬로그램': 'kg', '밀리리터': 'ml'}
def canonical(value):
    """사용자·LLM이 입력한 재료명을 비교 가능한 표준 이름으로 바꾼다.

    Args:
        value: 정규화할 재료명 문자열.

    Returns:
        NFKC 유니코드 정규화와 앞뒤 공백 제거 후 별칭 사전을 적용한 문자열.
        사전에 없는 이름은 정리된 원래 이름을 반환한다.
    """
    value = unicodedata.normalize('NFKC', value).strip()
    return ALIASES.get(value, value)

def normalize(recipe):
    """레시피 전체를 검증하고 재료명과 단위를 표준화한다.

    Args:
        recipe: ``Recipe``로 검증 가능한 사전 또는 Pydantic 모델.

    Returns:
        ``Recipe`` 스키마를 만족하는 일반 ``dict``. 재료 ``name``에는
        :func:`canonical`이, ``unit``에는 ``UNITS`` 매핑이 적용된다.

    Raises:
        pydantic.ValidationError: 필수 필드 누락, 잘못된 타입·범위 또는
            허용되지 않은 추가 필드가 있을 때.
    """
    data = Recipe.model_validate(recipe).model_dump()
    for item in data['ingredients']:
        item['name'] = canonical(item['name'])
        item['unit'] = UNITS.get(item['unit'], item['unit'])
    return data

def quality(recipe, transcript):
    """구조화된 재료가 실제 원문 근거와 일치하는지 보수적으로 검사한다.

    Args:
        recipe: :func:`normalize`를 통과한 레시피 사전.
        transcript: 자막 또는 사용자가 붙여 넣은 원문 문자열.

    Returns:
        발견된 문제를 설명하는 문자열 목록. 문제가 없으면 빈 목록이다.
        근거 포함 여부, 원문명과 표준명의 대응, 수량 단위 누락을 검사한다.
    """
    issues = []
    for item in recipe['ingredients']:
        if not item['evidence'] or item['evidence'] not in transcript:
            issues.append(f"{item['name']}: 원문 근거 확인 필요")
        if item['raw_name'] not in item['evidence'] or canonical(item['raw_name']) != item['name']:
            issues.append(f"{item['name']}: 원문 재료명과 정규화된 이름 확인 필요")
        if item['quantity'] is not None and not item['unit']:
            issues.append(f"{item['name']}: 수량 단위 확인 필요")
    return issues

def semantic(recipe, transcript):
    """검색과 필터에 사용할 버전형 시맨틱 파생 정보를 생성한다.

    Args:
        recipe: 정규화된 레시피 사전.
        transcript: 근거 원문. 현재 규칙에서는 인터페이스 일관성과 향후
            확장을 위해 받으며 직접 검색 문자열에 넣지는 않는다.

    Returns:
        시맨틱 버전, 추정 맵기, 맛 태그, 근거 재료, 제한적 알레르기 정보,
        임베딩용 ``search_text``를 포함한 사전. 추정할 근거가 없으면
        ``spice_level``은 0이 아니라 ``None``이다.
    """
    names = {x['name'] for x in recipe['ingredients']}
    # These are estimates, not objective heat measurements or safety certificates.
    evidence = [x for x in ('청양고추', '고춧가루', '고추장', '고추') if x in names]
    level = 3 if '청양고추' in names else (2 if evidence else None)
    tags = ['매운맛 추정'] if evidence else []
    allergens = set()
    mapping = {'달걀': '달걀', '우유': '우유', '버터': '우유', '치즈': '우유', '땅콩': '땅콩', '새우': '갑각류', '두부': '대두', '간장': '대두', '밀가루': '밀'}
    for name in names:
        if name in mapping:
            allergens.add(mapping[name])
    return {'version': 'recipe-semantic-v1', 'spice_level': level,
            'taste_tags': tags, 'evidence': evidence, 'origin': 'rule_estimate',
            'allergens': sorted(allergens), 'allergen_status': 'unverified',
            'search_text': ' '.join([recipe['title'], recipe['category'], *sorted(names), *tags, *recipe['steps']])}

class SearchInput(BaseModel):
    """검색·추천 API 요청의 검증 스키마.

    Attributes:
        query: 의미 검색에 사용할 자연어 질의.
        pantry: 사용자가 보유한 재료명 목록.
        max_time: 허용할 최대 조리 시간(분).
        max_missing: 허용할 최대 부족 재료 종류 수.
        min_spice: 요구하는 최소 맵기 추정값(0~5).
        exclude_ingredients: 결과에서 제외할 재료명 목록.
        allergens: 제외할 알레르기 항목. 미검증 레시피도 보수적으로 제외한다.
        tools: 사용 가능한 도구 목록. ``None``이면 도구 제한이 없다.
        tips: 상위 결과에 대해 Ollama 조리 팁을 생성할지 여부.
    """
    query: str = Field(default='', max_length=1000)
    pantry: list[str] = Field(default_factory=list, max_length=200)
    max_time: int | None = Field(default=None, ge=1)
    max_missing: int | None = Field(default=None, ge=0)
    min_spice: int | None = Field(default=None, ge=0, le=5)
    exclude_ingredients: list[str] = Field(default_factory=list)
    allergens: list[str] = Field(default_factory=list)
    tools: list[str] | None = None
    tips: bool = False
