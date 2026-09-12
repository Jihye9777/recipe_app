"""Recipe schemas and conservative, versioned semantic enrichment."""
import re
import unicodedata
from pydantic import BaseModel, ConfigDict, Field, field_validator

class Ingredient(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, allow_inf_nan=False)
    raw_name: str = Field(min_length=1)
    name: str = Field(min_length=1)
    quantity: float | None = Field(default=None, gt=0)
    unit: str | None = None
    optional: bool = False
    evidence: str = ''

class Recipe(BaseModel):
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
        if any(not x.strip() for x in values): raise ValueError('빈 조리 단계/도구는 사용할 수 없습니다.')
        return [x.strip() for x in values]

ALIASES = {'계란': '달걀', '고추가루': '고춧가루', '올리브오일': '올리브유'}
UNITS = {'스푼': None, '큰술': '큰술', '작은술': '작은술', '그램': 'g', '킬로그램': 'kg', '밀리리터': 'ml'}
def canonical(value):
    value = unicodedata.normalize('NFKC', value).strip()
    return ALIASES.get(value, value)

def normalize(recipe):
    data = Recipe.model_validate(recipe).model_dump()
    for item in data['ingredients']:
        item['name'] = canonical(item['name'])
        item['unit'] = UNITS.get(item['unit'], item['unit'])
    return data

def quality(recipe, transcript):
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
    query: str = Field(default='', max_length=1000)
    pantry: list[str] = Field(default_factory=list, max_length=200)
    max_time: int | None = Field(default=None, ge=1)
    max_missing: int | None = Field(default=None, ge=0)
    min_spice: int | None = Field(default=None, ge=0, le=5)
    exclude_ingredients: list[str] = Field(default_factory=list)
    allergens: list[str] = Field(default_factory=list)
    tools: list[str] | None = None
    tips: bool = False
