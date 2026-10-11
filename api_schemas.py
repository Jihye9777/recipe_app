"""FastAPI 요청·응답 문서용 스키마. 기존 브라우저 JSON 필드명을 유지한다."""

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class AnalyzeInput(BaseModel):
    """분석 입력. text가 있으면 URL 수집을 건너뛰며 작업 상태는 별도 조회한다."""

    url: str = Field(default='', description='YouTube URL. 직접 텍스트 입력 시 생략 가능', examples=['https://youtu.be/UUOpe_sTKzA'])
    text: str = Field(default='', description='직접 붙여 넣은 자막·레시피 텍스트', examples=['달걀 2개를 프라이팬에 익혀요.'])


class JobAccepted(BaseModel):
    """202 응답. job_id로 GET /api/jobs/{job_id}를 조회한다."""

    job_id: str


class RetryInput(BaseModel):
    """실패하거나 중단된 분석 작업의 재시도 요청."""

    job_id: str = Field(min_length=1, description='기존 분석 응답의 job_id')


class ReviewInput(RetryInput):
    """사용자 검토 승인. recipe 생략 시 대기 중인 결과를 사용한다."""

    approved: bool = Field(description='저장 승인 시 true')
    recipe: dict[str, Any] | None = Field(default=None, description='수정한 구조화 레시피. domain.Recipe 형식이며 재개 전에 검증한다')


class PantryInput(BaseModel):
    """냉장고 전체 목록 교체 요청. 빈 목록은 냉장고를 비운다."""

    pantry: list[str] = Field(default_factory=list, max_length=200, examples=[['계란', '양파']])


class PantryOutput(BaseModel):
    """정규화된 냉장고 재료명 목록."""

    pantry: list[str]


class ReindexInput(BaseModel):
    """SQLite 레시피 한 건의 재색인 요청."""

    id: str = Field(min_length=1, description='레시피 목록에 표시된 id')


class EmptyInput(BaseModel):
    """전체 재색인 요청 본문. 빈 JSON 객체 {}를 보낸다."""


class ImportInput(BaseModel):
    """과거 localStorage 레시피 이관. 잘못된 항목은 errors에 개별 보고한다."""

    recipes: list[dict[str, Any]] = Field(default_factory=list, description='id, title, ingredients(문자열 목록), steps를 가진 과거 레시피 목록')


class ImportOutput(BaseModel):
    """이관 처리 건수와 실패 항목의 오류 목록."""

    imported: int
    errors: list[str]


class RecipesOutput(BaseModel):
    """UI용 레시피 목록. 구조화 데이터·시맨틱·인덱스 상태를 포함한다."""

    recipes: list[dict[str, Any]]


class SearchOutput(RecipesOutput):
    """조건에 맞는 추천 목록과 선택적 AI 팁·폴백 경고."""

    tips: str
    warnings: list[str]


class JobOutput(BaseModel):
    """작업 상태. queued/running/review/complete/failed와 원래 결과를 반환한다."""

    id: str
    status: str
    stage: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    payload: dict[str, Any] | None = None


class ReindexOutput(BaseModel):
    """한 건 재색인 결과. 모델 등 기존 추가 필드도 보존한다."""

    model_config = ConfigDict(extra='allow')
    recipe: dict[str, Any]
    index_error: str | None


class ReindexAllOutput(BaseModel):
    """재색인 대상·성공·실패 건수 및 개별 오류."""

    total: int
    indexed: int
    failed: int
    failures: list[dict[str, Any]]


class ErrorOutput(BaseModel):
    """브라우저가 사용하는 오류 JSON. error를 유지하고 선택적으로 detail을 제공한다."""

    error: str
    detail: Any = None


class StatusOutput(BaseModel):
    """Ollama 서버 연결 여부와 선택한 생성 모델의 설치 상태."""

    running: bool
    model: str
    modelInstalled: bool
    models: list[str]


class HealthOutput(BaseModel):
    """구성 요소별 준비 상태. 실패 시 각 항목에 error가 추가될 수 있다."""

    ready: bool
    sqlite: dict[str, Any]
    ollama: dict[str, Any]
    embedding: dict[str, Any]
    qdrant: dict[str, Any]
