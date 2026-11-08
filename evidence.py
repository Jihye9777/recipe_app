"""시간·출처를 보존하는 수집 자료와 근거 기반 품질 검사."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

EVIDENCE_VERSION = 'recipe-sources-v2'
QUALITY_VERSION = 'multisource-evidence-v2'


class PartialFrameReadError(RuntimeError):
    """실패 전에 확보한 화면 출처를 보존하는 부분 판독 예외."""

    def __init__(self, sources):
        """완료된 Source 목록을 보관한다. 원문·이미지·파일은 변경하지 않는다."""
        super().__init__('일부 화면 판독에 실패해 앞서 확보한 자료만 보존했습니다.')
        self.sources = list(sources)


class Source(BaseModel):
    """한 원문 조각. 화면·시각 관찰은 실제 프레임 시점을 반드시 갖는다."""

    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    id: str = Field(min_length=1)
    kind: Literal['caption', 'description', 'screen_text', 'visual_action', 'speech', 'manual']
    text: str = Field(max_length=60000)
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, ge=0)
    language: str | None = None
    generated: bool | None = None
    frame_hash: str | None = None
    readable: bool = True

    @model_validator(mode='after')
    def valid_time(self):
        """입력 시점의 역전·누락을 거부하고 검증한 출처를 반환한다."""
        if (self.start is None) != (self.end is None):
            raise ValueError('시작과 끝 시점을 함께 지정하세요.')
        if self.start is not None and self.end < self.start:
            raise ValueError('출처 끝 시점은 시작 시점보다 빠를 수 없습니다.')
        if self.kind in {'screen_text', 'visual_action'} and self.start is None:
            raise ValueError('화면 근거에는 실제 프레임 시점이 필요합니다.')
        return self


class Correction(BaseModel):
    """원래 출처를 수정하지 않는 교정 연결. 양쪽 인용은 실제 출처에 있어야 한다."""

    model_config = ConfigDict(extra='forbid')
    source_id: str
    original: str = Field(min_length=1)
    target_source_id: str
    corrected: str = Field(min_length=1)


class SourceBundle(BaseModel):
    """수집 스냅샷. 원문·판독·경고를 JSON으로 보존하며 이미지는 저장하지 않는다."""

    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    version: Literal['recipe-sources-v2'] = EVIDENCE_VERSION
    revision: int = Field(default=1, ge=1)
    video_id: str = ''
    title: str = ''
    duration_seconds: float | None = Field(default=None, gt=0)
    sources: list[Source] = Field(default_factory=list)
    corrections: list[Correction] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    coverage: dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def unique_ids(self):
        """중복 출처 ID를 거부하고 검증한 묶음을 반환한다."""
        ids = [source.id for source in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError('출처 ID는 서로 달라야 합니다.')
        return self


def effective_sources(bundle):
    """교정 인용을 검증한 뒤 오타 구절만 제외한 출처 복제본을 반환한다.

    입력 SourceBundle은 변경하지 않는다. 화면에 없는 교정·중첩 교정은
    ValueError로 거부한다. 수정 값은 실제 화면 출처에만 남긴다.
    """
    bundle = SourceBundle.model_validate(bundle)
    sources = {source.id: source.model_copy(deep=True) for source in bundle.sources}
    used = set()
    for correction in bundle.corrections:
        origin = sources.get(correction.source_id)
        target = sources.get(correction.target_source_id)
        key = (correction.source_id, correction.original)
        if (not origin or not target or origin.kind not in {'caption', 'speech'}
                or target.kind != 'screen_text' or not target.readable
                or correction.original not in origin.text or correction.corrected not in target.text
                or key in used or correction.original == correction.corrected):
            raise ValueError('교정은 자막·음성 원문과 실제 화면 인용을 함께 확인해야 합니다.')
        if origin.start is None or abs(origin.start - target.start) > 15:
            raise ValueError('교정 출처의 시점이 서로 대응하지 않습니다.')
        origin.text = origin.text.replace(correction.original, '')
        used.add(key)
    return list(sources.values())


def effective_text(bundle):
    """유효한 교정만 반영한 검사 문자열을 반환한다. 원문 묶음은 그대로 보존한다."""
    return '\n'.join(source.text for source in effective_sources(bundle)
                     if source.readable and source.kind != 'visual_action')


def evidence_quality(recipe, facts, bundle):
    """후보·사실의 실제 출처와 독립 누락 신호를 검사해 검토 사유를 반환한다.

    inputs는 JSON 사전 또는 SourceBundle이다. 네트워크·파일 쓰기는 없으며,
    화면 샘플·모델 관찰을 영상 전체 검증으로 취급하지 않는다.
    """
    from domain import canonical
    from recipe_quality import COOKING, MENTION, _times, _clauses, inspect_recipe
    bundle = SourceBundle.model_validate(bundle)
    issues = list(bundle.warnings)
    try:
        sources = {source.id: source for source in effective_sources(bundle)}
        raw = effective_text(bundle)
    except ValueError as error:
        return list(dict.fromkeys(issues + [str(error)]))
    facts = facts.model_dump() if hasattr(facts, 'model_dump') else facts
    issues.extend(inspect_recipe(recipe, raw, facts))
    claims = [*recipe['ingredients'], *recipe.get('step_details', []),
              *facts.get('ingredients', []), *facts.get('steps', [])]
    for step in [*recipe.get('step_details', []), *facts.get('steps', [])]:
        claims.extend(step.get('ingredients', []))
    for claim in claims:
        ids = claim.get('source_ids', [])
        quote = claim.get('evidence', '')
        linked = [sources.get(source_id) for source_id in ids]
        if not ids or any(source is None for source in linked):
            issues.append('재료·단계의 출처 ID 확인이 필요합니다')
            continue
        if not any(source.readable and quote in source.text for source in linked):
            issues.append('재료·단계의 인용이 지정한 출처에 없습니다')
        if any(source.kind == 'visual_action' for source in linked):
            issues.append('화면 동작은 모델 관찰이므로 사용자 확인이 필요합니다')
    details = recipe.get('step_details', [])
    known_names = {canonical(item['name']) for item in facts.get('ingredients', [])}
    last_time = -1
    for step in details:
        timed = [sources[source_id].start for source_id in step.get('source_ids', [])
                 if source_id in sources and sources[source_id].start is not None]
        if timed:
            if min(timed) < last_time:
                issues.append('원본 영상의 조리 순서와 단계 순서가 다릅니다')
            last_time = max(last_time, min(timed))
    for source in sources.values():
        if not source.readable:
            issues.append('읽지 못한 화면 정보가 있어 확인이 필요합니다')
            continue
        if source.kind == 'visual_action':
            continue
        for clause in _clauses(source.text):
            if COOKING.search(clause) and not any(clause in step['evidence'] for step in details):
                issues.append('출처의 조리 동작이 최종 단계에 보존되지 않았습니다')
            for duration in _times(clause):
                if COOKING.search(clause) and not any(duration in _times(step['evidence'])
                        and clause in step['evidence'] for step in details):
                    issues.append('출처의 조리 시간이 같은 단계에 보존되지 않았습니다')
        for name, _, _ in MENTION.findall(source.text):
            name = canonical(re.sub(r'(?:은|는|을|를)$', '', name))
            if name not in known_names:
                issues.append(f'{name}: 출처에 있는 재료·분량이 사실 목록에서 누락됐습니다')
    return list(dict.fromkeys(issues))
