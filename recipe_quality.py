"""원문 사실·분량·단계 관계를 검증하는 네트워크 없는 순수 도메인 검사."""
import re
from fractions import Fraction

from domain import ALIASES, UNITS, canonical

QUALITY_VERSION = 'step-evidence-v1'
NUMBER = r'(?:\d+\s*/\s*\d+|\d+(?:\.\d+)?)'
UNIT = r'(?:큰술|작은술|스푼|밀리리터|킬로그램|그램|ml|kg|g|개|캔|컵|장|봉|줌)'
AMOUNT = re.compile(rf'({NUMBER})\s*({UNIT})(?![A-Za-z])', re.I)
MENTION = re.compile(rf'([가-힣A-Za-z]+)\s*({NUMBER})\s*({UNIT})(?![A-Za-z])', re.I)
TIME = re.compile(r'(\d+(?:\.\d+)?)\s*분(?:\s*(\d+(?:\.\d+)?)\s*초)?|(\d+(?:\.\d+)?)\s*초')
TOOLS = {'전자레인지': '전자레인지', '전자렌지': '전자레인지', '프라이팬': '프라이팬',
         '에어프라이어': '에어프라이어', '오븐': '오븐', '냄비': '냄비', '그릇': '그릇'}
COOKING = re.compile(r'넣|섞|익|끓|볶|굽|구워|삶|썰|자르|저어|버무|절여|불리|데우|가열|튀|올리|뿌리|녹|헹|씻|빼|덜|담')


def _fold(text):
    """비교용 입력에서 유니코드 분수만 보존형 ASCII 분수로 반환한다."""
    return str(text).replace('½', '1/2').replace('¼', '1/4').replace('¾', '3/4').replace('⁄', '/')


def _amounts(text):
    """지원하는 숫자·단위 표현을 정확한 유리수 쌍 목록으로 반환한다."""
    values = []
    for number, unit in AMOUNT.findall(_fold(text)):
        try:
            values.append((Fraction(number.replace(' ', '')), UNITS.get(unit.lower(), unit.lower())))
        except (ValueError, ZeroDivisionError):
            continue
    return values


def _names(name):
    """표준 재료명과 명시적 별칭을 비교 가능한 집합으로 반환한다."""
    name = canonical(name)
    return {name, *[alias for alias, target in ALIASES.items() if target == name]}


def _item_amounts(item, text):
    """재료명 바로 뒤의 명시적 분량만 반환해 다른 재료의 숫자와 혼동하지 않는다."""
    values = []
    for name in _names(item['name']) | {item['raw_name']}:
        for match in re.finditer(re.escape(name) + r'(?:은|는|을|를)?\s*[:=]?\s*', _fold(text)):
            amount = AMOUNT.match(_fold(text), match.end())
            if amount:
                values.extend(_amounts(amount.group()))
    return values


def _times(text):
    """분·초로 명시된 각 시간을 초 단위의 정확한 값으로 반환한다."""
    return [Fraction(minutes or '0') * 60 + Fraction(seconds or alone or '0')
            for minutes, seconds, alone in TIME.findall(text)]


def _tools(text):
    """지원되는 명시적 기구 표현의 표준명 집합을 반환한다."""
    return {name for token, name in TOOLS.items() if token in text}


def _clauses(text):
    """소수점은 유지하면서 문장·행 경계의 비어 있지 않은 구절을 반환한다."""
    return [part.strip() for part in re.split(r'(?<!\d)[.!?]|[.!?](?!\d)|[\n;]', text) if part.strip()]


def _quantity(item):
    """재료의 수량·단위를 비교용 쌍으로 반환하며 미상은 null로 둔다."""
    return (Fraction(str(item['quantity'])) if item['quantity'] is not None else None, item['unit'])


def _check_item(item, raw):
    """재료 주장의 원문명·인용·분량 지지를 검사해 사유 목록을 반환한다."""
    issues = []; name = item['name']; quote = item['evidence']
    if not quote or quote not in raw or item['raw_name'] not in quote or canonical(item['raw_name']) != canonical(name):
        issues.append(f'{name}: 원문 재료 근거 확인 필요')
    amounts = _item_amounts(item, quote)
    if item['quantity'] is not None and _quantity(item) not in amounts:
        issues.append(f'{name}: 수량·단위가 해당 원문 근거와 다릅니다')
    if item['quantity'] is None and amounts:
        issues.append(f'{name}: 원문에 명시된 분량이 누락됐습니다')
    return issues


def _check_step(step, raw):
    """한 단계의 인용·조리 동작·기구·시간 연결을 검사한다. 부작용은 없다."""
    issues = []; quote = step['evidence']; action = step['action']
    if quote not in raw or action not in quote or not COOKING.search(action):
        issues.append('조리 동작과 원문 근거 확인 필요')
    if action.rstrip('. ') != quote.rstrip('. '):
        issues.append('원문 조리 행위가 사실 추출에서 축약됐습니다')
    if len(_clauses(quote)) > 1:
        issues.append('여러 원문 행위의 기구·시간 연결 확인 필요')
    if re.search(r'쓰지|사용하지|넣지|금지|말고|아니라', quote):
        issues.append('부정·대체 지시의 적용 범위 확인 필요')
    tools = {TOOLS.get(tool, tool) for tool in step['tools']}
    if any(not any(alias in quote for alias, name in TOOLS.items() if name == tool)
           if tool in TOOLS.values() else tool not in quote for tool in tools):
        issues.append('원문에 없는 조리 기구가 추가됐습니다')
    if _tools(quote) - tools:
        issues.append('원문의 조리 기구가 단계에서 누락됐습니다')
    times = _times(quote); duration = step['duration_seconds']
    if step['duration_text'] is not None and (duration is None or step['duration_text'] not in quote):
        issues.append('시간 값과 원문 시간 표현의 근거가 일치하지 않습니다')
    if times and (duration is None or Fraction(str(duration)) not in times):
        issues.append('원문 조리 시간이 누락되거나 변경됐습니다')
    if duration is not None and (Fraction(str(duration)) not in times
                                or not step['duration_text'] or step['duration_text'] not in quote
                                or _times(step['duration_text']) != [Fraction(str(duration))]):
        issues.append('시간 값과 원문 시간 표현의 근거가 일치하지 않습니다')
    for item in step['ingredients']:
        issues.extend(_check_item(item, quote))
    for name, number, unit in MENTION.findall(_fold(quote)):
        name = canonical(re.sub(r'(?:은|는|을|를)$', '', name))
        expected = _amounts(number + unit)
        if not any(canonical(item['name']) == name and _quantity(item) in expected
                   for item in step['ingredients']):
            issues.append(f'{name}: 단계의 명시적 재료·분량이 누락됐습니다')
    return issues


def source_quality(facts, raw):
    """모델 사실 목록과 지원되는 원문 표현을 대조해 누락·모순 사유를 반환한다."""
    facts = facts.model_dump() if hasattr(facts, 'model_dump') else facts
    issues = []
    if not facts['ingredients'] or not facts['steps']:
        issues.append('원문 재료·조리 사실을 충분히 확보하지 못했습니다')
    for item in facts['ingredients']:
        issues.extend(_check_item(item, raw))
        if item.get('amount_role') == 'partial':
            issues.append(f"{item['name']}: 부분 사용량과 전체 분량 관계 확인 필요")
    for step in facts['steps']:
        issues.extend(_check_step(step, raw))
    for name, number, unit in MENTION.findall(_fold(raw)):
        name = canonical(re.sub(r'(?:은|는|을|를)$', '', name))
        matches = [item for item in facts['ingredients'] if canonical(item['name']) == name]
        expected = _amounts(number + unit)
        if not matches or not any(_quantity(item) in expected for item in matches):
            issues.append(f'{name}: 명시적 원문 분량을 사실 목록에서 확인하지 못했습니다')
    for clause in _clauses(raw):
        if not (_tools(clause) or _times(clause)) or not COOKING.search(clause):
            continue
        if not any(clause in step['evidence'] and _tools(clause) <= {TOOLS.get(t, t) for t in step['tools']}
                   and all(step['duration_seconds'] is not None and Fraction(str(step['duration_seconds'])) == time
                           for time in _times(clause)) for step in facts['steps']):
            issues.append('원문의 기구·시간이 같은 조리 사실에 보존되지 않았습니다')
    return list(dict.fromkeys(issues))


def inspect_recipe(recipe, raw, facts):
    """고정된 원문 사실과 최종 레시피를 비교해 자동 저장을 막을 사유를 반환한다."""
    facts = facts.model_dump() if hasattr(facts, 'model_dump') else facts
    issues = source_quality(facts, raw)
    details = recipe.get('step_details', [])
    if len(details) != len(facts['steps']) or len(recipe['steps']) != len(details):
        issues.append('원문 조리 단계 또는 단계별 구조 정보가 누락됐습니다')
    source_names = {canonical(item['name']) for item in facts['ingredients']}
    final_names = {item['name'] for item in recipe['ingredients']}
    for name in source_names - final_names:
        issues.append(f'{name}: 원문 재료가 최종 재료 목록에서 누락됐습니다')
    for name in final_names - source_names:
        issues.append(f'{name}: 독립 원문 사실에 없는 재료입니다')
    for item in recipe['ingredients']:
        issues.extend(_check_item(item, raw))
        matching = [fact for fact in facts['ingredients'] if canonical(fact['name']) == item['name']]
        quantities = {_quantity(fact) for fact in matching}
        if matching and (len(quantities) != 1 or _quantity(item) not in quantities):
            issues.append(f"{item['name']}: 원문 사실과 최종 분량이 다르거나 충돌합니다")
    for index, step in enumerate(details):
        issues.extend(_check_step(step, raw))
        source_index = step['source_step']
        if source_index != index or source_index is None or source_index >= len(facts['steps']):
            issues.append('조리 단계와 원문 단계 연결을 확인해야 합니다')
            continue
        fact = facts['steps'][source_index]
        if step['action'] != fact['action'] or step['evidence'] != fact['evidence']:
            issues.append('원문 조리 행위·조건이 축약되거나 변경됐습니다')
        if set(step['tools']) != set(fact['tools']) or step['duration_seconds'] != fact['duration_seconds']:
            issues.append('같은 단계의 조리 기구·시간이 원문 사실과 다릅니다')
        uses = {(canonical(i['name']), _quantity(i)) for i in step['ingredients']}
        expected = {(canonical(i['name']), _quantity(i)) for i in fact['ingredients']}
        if uses != expected or any(name not in final_names for name, _ in uses):
            issues.append('단계 재료·분량이 원문 또는 전체 재료 목록과 다릅니다')
        if index < len(recipe['steps']):
            prose = recipe['steps'][index]
            if prose.rstrip('. ') != render_steps([step])[0].rstrip('. '):
                issues.append('표시 문장이 근거 기반 조리 단계와 다릅니다')
            if not COOKING.search(prose) or not _tools(step['evidence']) <= _tools(prose):
                issues.append('표시 문장에 조리 동작·기구가 누락됐습니다')
            if step['duration_seconds'] is not None and Fraction(str(step['duration_seconds'])) not in _times(prose):
                issues.append('표시 문장에 조리 시간이 누락되거나 변경됐습니다')
            if any(amount not in _amounts(step['evidence']) for amount in _amounts(prose)) or _tools(prose) - _tools(step['evidence']) or any(t not in _times(step['evidence']) for t in _times(prose)):
                issues.append('표시 문장에 원문에 없는 수량·기구·시간이 추가됐습니다')
    required_tools = {tool for step in details for tool in step['tools']}
    if not required_tools <= set(recipe['tools']) or any(tool not in raw for tool in recipe['tools']):
        issues.append('전체 조리 도구 목록과 단계·원문이 일치하지 않습니다')
    return list(dict.fromkeys(issues))


def render_steps(details):
    """구조화 단계의 확인된 재료·기구·시간을 빠뜨리지 않는 표시 문장을 반환한다."""
    result = []
    for step in details:
        step = step.model_dump() if hasattr(step, 'model_dump') else step
        text = step['action'].rstrip('. ')
        extra = []
        for item in step['ingredients']:
            if not any(name in text for name in _names(item['name'])) or (item['quantity'] is not None and _quantity(item) not in _item_amounts(item, text)):
                amount = '' if item['quantity'] is None else f" {item['quantity']:g}{item['unit'] or ' (확인 어려움)'}"
                extra.append(item['name'] + amount)
        for tool in step['tools']:
            if tool not in text: extra.append(tool)
        if step['duration_seconds'] is not None and Fraction(str(step['duration_seconds'])) not in _times(text):
            extra.append(step['duration_text'] or f"{step['duration_seconds']:g}초")
        result.append(text + ('. ' + ' · '.join(extra) if extra else '') + '.')
    return result
