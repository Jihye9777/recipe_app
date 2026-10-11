"""한입노트의 로컬 HTTP API, 정적 파일 제공, YouTube 수집 진입점."""

from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json
import os
import re
import tempfile
import uuid
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from contextlib import asynccontextmanager
from typing import Any
from fastapi import FastAPI, Request as APIRequest
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.concurrency import run_in_threadpool
from api_schemas import (AnalyzeInput, JobAccepted, RetryInput, ReviewInput,
    PantryInput, PantryOutput, ReindexInput, EmptyInput, ImportInput, ImportOutput,
    RecipesOutput, SearchOutput, JobOutput, ReindexOutput, ReindexAllOutput, ErrorOutput,
    StatusOutput, HealthOutput)
from storage import Store, public
from integrations import Ollama, QdrantIndex
from workflows import Pipelines
from domain import normalize, semantic, canonical, SearchInput
from health import service_health

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
load_dotenv(ROOT / '.env')

# This personal app must not send recipe/checkpoint content to cloud tracing services.
os.environ['LANGSMITH_TRACING'] = 'false'
os.environ['LANGCHAIN_TRACING_V2'] = 'false'

# Windows TEMP 권한 문제를 피하기 위해 앱 임시 파일을 전용 폴더에 만듭니다.
RUNTIME_DIR = Path(os.environ.get('RECIPE_RUNTIME_DIR', str(ROOT / '.runtime'))).resolve()
os.environ["TEMP"] = str(RUNTIME_DIR)
os.environ["TMP"] = str(RUNTIME_DIR)
tempfile.tempdir = str(RUNTIME_DIR)
# 개발 도구가 남긴 잘못된 프록시(127.0.0.1:9)를 무시하고 YouTube에 직접 연결합니다.
# 이 설정은 이 앱 프로세스에만 적용됩니다.
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

DATA_DIR = Path(os.environ.get('RECIPE_DATA_DIR',str(ROOT / 'data')))
STORE = None
PIPELINES = None
WORKER = None
ACTIVE = set()
ACTIVE_LOCK = Lock()
PIPELINES_LOCK = Lock()

def pipelines():
    """공유 LangGraph 파이프라인 묶음을 최초 요청 시 한 번 생성한다.

    Returns:
        SQLite 저장소, Ollama, Qdrant Local, 자막 추출기와 체크포인트 DB가
        연결된 :class:`workflows.Pipelines` 싱글턴.

    Side Effects:
        첫 호출에서 Qdrant Local 파일 잠금과 체크포인트 SQLite 연결을 연다.
        이후 호출은 동일 객체를 반환한다.
    """
    global PIPELINES
    with PIPELINES_LOCK:
        if PIPELINES is None:
            llm = Ollama()
            qdrant_path = os.environ.get('QDRANT_PATH')
            PIPELINES = Pipelines(STORE, llm, QdrantIndex(llm, qdrant_path or DATA_DIR / 'qdrant'), extract_transcript, str(DATA_DIR / 'checkpoints.db'))
    return PIPELINES

def submit_job(id, payload=None, resume=None):
    """수집 그래프 실행·재개를 단일 백그라운드 작업자에게 제출한다.

    Args:
        id: jobs 테이블과 LangGraph thread ID로 사용할 작업 UUID.
        payload: 새 작업 입력 ``{'url': str, 'text': str}``. 재시도 또는 검토
            재개에서는 ``None``일 수 있다.
        resume: 사용자 확인을 재개할 승인·수정 사전. 일반 실행에서는 ``None``.

    Returns:
        반환값 없음. 실제 결과와 오류는 ``jobs`` 테이블에서 조회한다.

    Raises:
        ValueError: 동일 ID의 작업이 현재 프로세스에서 이미 실행 중일 때.

    Side Effects:
        작업을 queued로 기록하고 ``WORKER`` 큐에 추가한다.
    """
    with ACTIVE_LOCK:
        if id in ACTIVE: raise ValueError('이미 처리 중인 작업입니다.')
        ACTIVE.add(id)
        STORE.job(id,status='queued')
    def work():
        """백그라운드 스레드에서 그래프를 실행하고 활성 작업 표시를 정리한다.

        Returns:
            반환값 없음.

        Notes:
            그래프 바깥까지 나온 예외는 jobs의 failed 상태로 저장하며, 성공과
            실패 모두 ``ACTIVE`` 집합에서 작업 ID를 제거한다.
        """
        try: pipelines().run(id,payload,resume)
        except Exception as e: STORE.job(id,status='failed',error=str(e))
        finally:
            with ACTIVE_LOCK: ACTIVE.discard(id)
    WORKER.submit(work)

def video_id_from_url(value):
    """여러 YouTube URL 표현에서 영상 ID 후보를 추출한다.

    Args:
        value: 파싱할 URL 문자열.

    Returns:
        공유 URL 경로, ``v`` 쿼리, embed/shorts/live 경로에서 찾은 ID 문자열.
        ID 후보가 없으면 ``None``. 길이와 호스트의 엄격한 검증은
        :func:`workflows.valid_video`에서 수행한다.
    """
    parsed = urlparse(value)
    if parsed.hostname in {"youtu.be", "www.youtu.be"}:
        return parsed.path.strip("/").split("/")[0]
    query_id = parse_qs(parsed.query).get("v", [None])[0]
    if query_id:
        return query_id
    match = re.search(r"(?:embed|shorts|live)/([\w-]{6,})", parsed.path)
    return match.group(1) if match else None

def transcript_from_youtube_transcript_api(video_id):
    """youtube-transcript-api로 공개 한국어·영어 자막을 가져온다.

    Args:
        video_id: 자막을 요청할 YouTube 영상 ID.

    Returns:
        ``(자막 전체 문자열, 언어 코드, 사용자 표시용 출처 설명)`` 튜플.
        각 자막 조각의 빈 텍스트를 제외하고 공백으로 연결한다.

    Raises:
        RuntimeError: 라이브러리가 없거나 반환된 자막이 비어 있을 때.
        youtube_transcript_api의 예외: 자막 부재, 비공개 영상, 요청 차단 등.

    Notes:
        시스템 프록시 환경변수를 사용하지 않으며 요청 기본 제한 시간은
        연결 5초, 읽기 20초이다.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from requests import Session
    except ImportError:
        raise RuntimeError("youtube-transcript-api가 설치되어 있지 않아요.")
    class TranscriptSession(Session):
        """모든 자막 HTTP 요청에 기본 timeout을 추가하는 requests 세션."""

        def request(self, *args, **kwargs):
            """requests의 원래 인자를 전달하되 timeout이 없으면 기본값을 넣는다.

            Args:
                *args: ``requests.Session.request``의 위치 인자.
                **kwargs: 동일 메서드의 키워드 인자. ``timeout``을 직접 주면
                    호출자 값을 유지한다.

            Returns:
                ``requests.Response`` 객체.

            Raises:
                requests.RequestException: HTTP 요청에 실패했을 때.
            """
            kwargs.setdefault('timeout',(5,20))
            return super().request(*args,**kwargs)
    # requests가 시스템 프록시 환경 변수를 따르지 않도록 합니다.
    with TranscriptSession() as http_client:
        http_client.trust_env = False
        fetched = YouTubeTranscriptApi(http_client=http_client).fetch(video_id, languages=["ko", "en"])
    transcript = " ".join(item.text.strip() for item in fetched if item.text.strip()).strip()
    if not transcript:
        raise RuntimeError("youtube-transcript-api에서 빈 자막이 반환됐어요.")
    return transcript, fetched.language_code, f"YouTube 자막 · {fetched.language}"

def transcript_from_local_whisper(video_url):
    """YouTube 오디오를 임시 다운로드하고 로컬 Whisper로 텍스트화한다.

    Args:
        video_url: pytubefix가 열 수 있는 정규화된 YouTube URL.

    Returns:
        ``(한국어 인식 문자열, 'ko', 사용자 표시용 Whisper 출처)`` 튜플.

    Raises:
        RuntimeError: 의존 패키지·오디오 스트림·인식 텍스트가 없을 때.
        pytubefix 또는 faster_whisper의 예외: 다운로드나 음성 인식에 실패할 때.

    Side Effects:
        오디오를 ``RUNTIME_DIR``에 임시 저장하고 Whisper 모델을
        ``RUNTIME_DIR/whisper-models``에 캐시한다. 오디오는 성공·실패와
        관계없이 가능한 경우 삭제한다.
    """
    try:
        from faster_whisper import WhisperModel
        from pytubefix import YouTube
    except ImportError:
        raise RuntimeError("로컬 음성 인식 패키지가 설치되어 있지 않아요.")

    audio_path = None
    try:
        video = YouTube(video_url)
        audio_stream = video.streams.get_audio_only()
        if audio_stream is None:
            audio_stream = video.streams.filter(only_audio=True).order_by("abr").desc().first()
        if audio_stream is None:
            raise RuntimeError("영상에서 오디오 스트림을 찾지 못했어요.")
        audio_path = audio_stream.download(
            output_path=str(RUNTIME_DIR),
            filename=f"whisper-{uuid.uuid4().hex}.mp4",
            timeout=30,
            max_retries=1,
        )
        model_name = os.environ.get("WHISPER_MODEL", "base")
        model = WhisperModel(model_name, device="cpu", compute_type="int8",download_root=str(RUNTIME_DIR/'whisper-models'))
        segments, _ = model.transcribe(audio_path, language="ko", vad_filter=True)
        transcript = " ".join(segment.text.strip() for segment in segments).strip()
        if not transcript:
            raise RuntimeError("영상 음성에서 텍스트를 만들지 못했어요.")
        return transcript, "ko", f"로컬 Whisper · {model_name}"
    finally:
        if audio_path:
            try:
                Path(audio_path).unlink(missing_ok=True)
            except OSError:
                pass

def extract_transcript(video_url):
    """자막 API를 우선 사용하고 실패하면 로컬 Whisper로 폴백한다.

    Args:
        video_url: 사용자가 제출한 YouTube URL.

    Returns:
        성공한 수집기의 ``(텍스트, 언어 코드, 출처 설명)`` 튜플.

    Raises:
        ValueError: URL에서 영상 ID를 얻지 못할 때.
        RuntimeError: 자막 API와 로컬 Whisper가 모두 실패했을 때. 메시지에는
            두 실패 원인이 함께 포함된다.
    """
    video_id = video_id_from_url(video_url)
    if not video_id:
        raise ValueError("유효한 YouTube 주소를 입력해 주세요.")
    try:
        return transcript_from_youtube_transcript_api(video_id)
    except Exception as error:
        subtitle_error = error
    try:
        return transcript_from_local_whisper(video_url)
    except Exception as whisper_error:
        raise RuntimeError(f"자막 API: {subtitle_error} / 로컬 Whisper: {whisper_error}")

@asynccontextmanager
async def lifespan(application: FastAPI):
    """서버 시작·종료에 자원을 연결한다.

    Args:
        application: 수명을 관리할 FastAPI 앱.
    Yields:
        초기화된 서버의 요청 처리 구간.
    Side Effects:
        전용 임시 폴더·SQLite·단일 작업자를 준비한다. 종료 시 진행 작업을
        기다리고 체크포인트·Qdrant 파일 잠금을 닫는다. import만으로 DB를 열지 않는다.
    """
    global STORE, WORKER, PIPELINES
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if STORE is None:
        STORE = Store(DATA_DIR / 'recipe.db')
    WORKER = ThreadPoolExecutor(max_workers=1)
    try:
        yield
    finally:
        await run_in_threadpool(WORKER.shutdown, wait=True)
        WORKER = None
        try:
            if PIPELINES is not None:
                try:
                    PIPELINES.checkpoint_db.close()
                finally:
                    PIPELINES.index.close()
        finally:
            PIPELINES = None
            STORE = None
            ACTIVE.clear()


ERROR_RESPONSES = {
    code: {'model': ErrorOutput, 'description': description}
    for code, description in {
        404: '대상을 찾을 수 없음', 415: 'JSON Content-Type 필요',
        422: '입력 또는 작업 상태 오류', 502: '외부 연결 오류',
        500: '예상하지 못한 서버 오류',
    }.items()
}
app = FastAPI(
    title='한입노트 API', version='1.0.0',
    description='로컬 레시피 북 API. 분석은 202의 job_id로 상태를 조회합니다. '
                'Try it out의 저장·분석·재색인 요청은 실제 데이터를 변경합니다.',
    lifespan=lifespan, responses=ERROR_RESPONSES,
    openapi_tags=[
        {'name': '상태', 'description': 'SQLite·Ollama·Qdrant 준비 상태'},
        {'name': '레시피', 'description': '원본 조회와 과거 데이터 이관'},
        {'name': '분석', 'description': '비동기 분석·검토·재시도'},
        {'name': '냉장고', 'description': '보유 재료 조회·교체'},
        {'name': '검색', 'description': '재료·의미 검색과 추천'},
        {'name': '인덱스', 'description': '원본을 보존하며 검색 인덱스 재생성'},
    ],
)


class JSONBodyLimit:
    """API POST 본문을 2MB 이내 JSON 객체로 제한하는 ASGI 미들웨어."""

    def __init__(self, app):
        """다음 ASGI 앱을 보관한다. 외부 호출·파일 쓰기는 수행하지 않는다."""
        self.application = app

    async def __call__(self, scope, receive, send):
        """본문을 제한 내에서 수집·검증하고 FastAPI에 재전달한다.

        Args:
            scope, receive, send: ASGI 연결 정보와 수신·송신 콜백.
        Returns:
            없음. 유효 본문은 전달하고 잘못된 본문은 오류 JSON으로 응답한다.
        """
        if scope['type'] != 'http' or scope['method'] != 'POST' or not scope['path'].startswith('/api/'):
            await self.application(scope, receive, send)
            return
        headers = dict(scope['headers'])
        content_type = headers.get(b'content-type', b'').decode().split(';')[0].strip().lower()
        if content_type != 'application/json':
            await JSONResponse({'error': 'application/json 요청만 지원합니다.'}, status_code=415)(scope, receive, send)
            return
        try:
            if b'content-length' in headers:
                size = int(headers[b'content-length'])
                if not 1 <= size <= 2_000_000:
                    raise ValueError('요청 크기를 확인해 주세요.')
            body = bytearray()
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                body.extend(message.get('body', b''))
                if len(body) > 2_000_000:
                    raise ValueError('요청 크기를 확인해 주세요.')
                if not message.get('more_body', False):
                    break
            if not body:
                raise ValueError('요청 크기를 확인해 주세요.')
            parsed = json.loads(body.decode('utf-8'))
            if not isinstance(parsed, dict):
                raise ValueError('JSON 객체가 필요합니다.')
        except (ValueError, UnicodeError) as error:
            await JSONResponse({'error': str(error)}, status_code=422)(scope, receive, send)
            return

        delivered = False

        async def replay_body():
            """검증한 본문을 한 번 전달한 후 실제 연결 수신을 계속한다."""
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()

        await self.application(scope, replay_body, send)


app.add_middleware(JSONBodyLimit)


@app.exception_handler(RequestValidationError)
async def validation_error(request: APIRequest, error: RequestValidationError):
    """Pydantic 입력 오류를 기존 error 필드의 422 JSON으로 변환한다."""
    issues = [{'loc': list(x['loc']), 'msg': x['msg'], 'type': x['type']} for x in error.errors()]
    return JSONResponse({'error': '입력값을 확인해 주세요.', 'detail': issues}, status_code=422)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: APIRequest, error: StarletteHTTPException):
    """404·405 등 HTTP 오류를 JSON으로 반환한다. 원래 상태 코드를 보존한다."""
    return JSONResponse({'error': str(error.detail)}, status_code=error.status_code, headers=error.headers)


async def business_error(request: APIRequest, error: Exception):
    """입력·업무 상태 예외를 422로 반환한다. 원본 저장소는 변경하지 않는다."""
    return JSONResponse({'error': str(error)}, status_code=422)


for error_type in (ValueError, RuntimeError, KeyError, TypeError):
    app.add_exception_handler(error_type, business_error)


async def connection_error(request: APIRequest, error: Exception):
    """외부 연결 오류를 502 JSON으로 반환한다."""
    return JSONResponse({'error': '외부 서비스에 연결하지 못했어요.', 'detail': str(error)}, status_code=502)


for error_type in (HTTPError, URLError, TimeoutError):
    app.add_exception_handler(error_type, connection_error)


@app.exception_handler(Exception)
async def unexpected_error(request: APIRequest, error: Exception):
    """예상하지 못한 오류를 500 JSON으로 반환한다."""
    return JSONResponse({'error': '분석 중 알 수 없는 오류가 발생했어요.', 'detail': str(error)}, status_code=500)


@app.get('/api/health', tags=['상태'], summary='전체 구성 요소 준비 상태', response_model=HealthOutput)
def get_health() -> dict[str, Any]:
    """SQLite·Ollama·임베딩·Qdrant를 검사한 준비 상태 사전을 반환한다."""
    return service_health(STORE, pipelines().index)


@app.get('/api/status', tags=['상태'], summary='Ollama 실행 및 생성 모델 상태', response_model=StatusOutput)
def get_status() -> dict[str, Any]:
    """Ollama 모델 목록을 조회한다. 연결 실패도 running=false인 200으로 반환한다."""
    base_url = os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
    model = os.environ.get('OLLAMA_MODEL', 'gemma4:latest')
    try:
        request = Request(f'{base_url}/api/tags', headers={'User-Agent': 'HanipNote'})
        with urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode())
        names = [item.get('name') for item in payload.get('models', [])]
        installed = model in names or (':' not in model and model + ':latest' in names)
        return {'running': True, 'model': model, 'modelInstalled': installed, 'models': names}
    except Exception:
        return {'running': False, 'model': model, 'modelInstalled': False, 'models': []}


@app.get('/api/recipes', tags=['레시피'], summary='저장된 레시피 목록·상세', response_model=RecipesOutput)
def get_recipes():
    """SQLite 전체 원본을 UI 공개 형식의 recipes 목록으로 반환한다."""
    return {'recipes': [public(row) for row in STORE.all()]}


@app.get('/api/pantry', tags=['냉장고'], summary='보유 재료 조회', response_model=PantryOutput)
def get_pantry():
    """저장된 냉장고 재료명 목록을 반환한다. 데이터를 변경하지 않는다."""
    return {'pantry': STORE.pantry()}


@app.get('/api/jobs/{job_id}', tags=['분석'], summary='분석 작업 상태·결과 조회', response_model=JobOutput)
def get_job(job_id: str):
    """작업 ID로 상태 사전을 조회한다. 없는 ID는 404 오류 JSON을 반환한다."""
    job = STORE.job(job_id)
    if job is None:
        raise StarletteHTTPException(404, '작업이 없습니다.')
    return job


@app.post('/api/analyze', tags=['분석'], summary='URL 또는 텍스트 분석 시작', status_code=202, response_model=JobAccepted)
def analyze(body: AnalyzeInput):
    """url/text 요청을 큐에 넣고 job_id를 반환한다. 완료 결과는 상태 API로 조회한다."""
    payload = {'url': body.url.strip(), 'text': body.text.strip()}
    job_id = str(uuid.uuid4())
    STORE.job(job_id, status='queued', payload=payload)
    submit_job(job_id, payload)
    return {'job_id': job_id}


def resume_job(job_id: str, review: ReviewInput | None = None):
    """기존 작업 상태를 검사하고 재시도 또는 승인 결과로 재개한다.

    Args:
        job_id: 저장된 작업 ID.
        review: 검토 승인 요청. None이면 실패·중단 작업을 재시도한다.
    Returns:
        재개된 작업의 job_id 사전.
    Raises:
        ValueError: 작업 상태·승인·수정 레시피가 유효하지 않을 때.
    """
    job = STORE.job(job_id)
    if not job or job['status'] not in {'review', 'failed', 'running', 'queued'}:
        raise ValueError('재개할 작업이 없습니다.')
    if review is not None:
        if job['status'] != 'review':
            raise ValueError('확인 대기 중인 작업이 아닙니다.')
        if review.approved is not True:
            raise ValueError('확인 후 저장해 주세요.')
        payload = review.model_dump()
        payload['recipe'] = normalize(review.recipe or job['result']['recipe'])
        submit_job(job_id, resume=payload)
    else:
        if job['status'] == 'review':
            raise ValueError('검토 내용을 확인해 주세요.')
        submit_job(job_id)
    return {'job_id': job_id}


@app.post('/api/review', tags=['분석'], summary='검토 승인·수정 후 저장', status_code=202, response_model=JobAccepted)
def review_job(body: ReviewInput):
    """검토 입력을 검증해 재개한다. 실패 시 대기 체크포인트를 보존한다."""
    return resume_job(body.job_id, body)


@app.post('/api/retry', tags=['분석'], summary='실패·중단 분석 재시도', status_code=202, response_model=JobAccepted)
def retry_job(body: RetryInput):
    """기존 작업 ID로 수집을 재시도하고 같은 job_id를 반환한다."""
    return resume_job(body.job_id)


@app.post('/api/pantry', tags=['냉장고'], summary='냉장고 목록 교체', response_model=PantryOutput)
def save_pantry(body: PantryInput):
    """입력 재료명을 정규화·중복 제거해 SQLite에 교체 저장하고 반환한다."""
    return {'pantry': STORE.pantry(sorted({canonical(item) for item in body.pantry if item.strip()}))}


@app.post('/api/search', tags=['검색'], summary='재료·자연어·조건 추천', response_model=SearchOutput)
def search(body: SearchInput):
    """검색 입력을 단일 작업자에 제출한다. 결과·팁·경고 사전을 기다려 반환한다."""
    request = body.model_dump()
    future = WORKER.submit(lambda: pipelines().search.invoke({'request': request})['result'])
    return future.result()


@app.post('/api/reindex', tags=['인덱스'], summary='레시피 한 건 재색인', response_model=ReindexOutput)
def reindex(body: ReindexInput):
    """입력 id 원본을 단일 작업자에서 재색인해 결과를 반환한다. 원본은 보존한다."""
    return WORKER.submit(lambda: pipelines().reindex(body.id)).result()


@app.post('/api/reindex-all', tags=['인덱스'], summary='대기·실패 레시피 일괄 재색인', response_model=ReindexAllOutput)
def reindex_all(body: EmptyInput):
    """현재 백엔드·모델에 재색인이 필요한 원본만 처리하고 성공·실패 요약을 반환한다."""
    return WORKER.submit(lambda: pipelines().reindex_all()).result()


@app.post('/api/import', tags=['레시피'], summary='과거 브라우저 레시피 이관', response_model=ImportOutput)
def import_recipes(body: ImportInput):
    """과거 입력을 원본에 멱등 저장하고 처리 건수·항목별 오류 목록을 반환한다."""
    count = 0
    errors = []
    for old in body.recipes:
        try:
            recipe = normalize({
                'title': old['title'], 'category': old.get('category', '요리'),
                'time': old.get('time') or None,
                'ingredients': [{'raw_name': item, 'name': item} for item in old['ingredients']],
                'steps': old['steps'],
            })
            key = 'legacy:' + str(old['id'])
            STORE.save(str(uuid.uuid5(uuid.NAMESPACE_URL, key)), key, old.get('source', ''),
                       '', recipe, semantic(recipe, ''), 'legacy')
            count += 1
        except (ValueError, KeyError, TypeError) as error:
            errors.append(str(error))
    return {'imported': count, 'errors': errors}


@app.get('/', include_in_schema=False)
@app.get('/{path:path}', include_in_schema=False)
def frontend(path: str = ''):
    """허용한 UI 파일만 제공한다. 설정·소스·DB·임시 파일·기타 경로는 404다."""
    files = {'': 'index.html', 'index.html': 'index.html', 'app.js': 'app.js',
             'styles.css': 'styles.css', 'assets/og.png': 'assets/og.png'}
    if path not in files:
        raise StarletteHTTPException(404, 'Not found')
    file = ROOT / files[path]
    if not file.is_file():
        raise StarletteHTTPException(404, 'Not found')
    return FileResponse(file)


if __name__ == '__main__':
    import uvicorn

    host = os.environ.get('APP_HOST', '127.0.0.1')
    port = int(os.environ.get('APP_PORT', '8000'))
    display_host = 'localhost' if host in {'127.0.0.1', 'localhost'} else host
    print(f'한입노트가 http://{display_host}:{port} 에서 실행됩니다.', flush=True)
    print(f'API 문서: http://{display_host}:{port}/docs', flush=True)
    uvicorn.run(app, host=host, port=port, workers=1)
