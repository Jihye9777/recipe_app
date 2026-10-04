"""한입노트의 로컬 HTTP API, 정적 파일 제공, YouTube 수집 진입점."""

from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
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
RUNTIME_DIR.mkdir(exist_ok=True)
os.environ["TEMP"] = str(RUNTIME_DIR)
os.environ["TMP"] = str(RUNTIME_DIR)
tempfile.tempdir = str(RUNTIME_DIR)
# 개발 도구가 남긴 잘못된 프록시(127.0.0.1:9)를 무시하고 YouTube에 직접 연결합니다.
# 이 설정은 이 앱 프로세스에만 적용됩니다.
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

DATA_DIR = Path(os.environ.get('RECIPE_DATA_DIR',str(ROOT / 'data')))
DATA_DIR.mkdir(exist_ok=True)
STORE = Store(DATA_DIR / 'recipe.db')
PIPELINES = None
WORKER = ThreadPoolExecutor(max_workers=1)
ACTIVE = set()
ACTIVE_LOCK = Lock()

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
    if PIPELINES is None:
        llm = Ollama()
        qdrant_path = os.environ.get('QDRANT_PATH')
        PIPELINES = Pipelines(STORE, llm, QdrantIndex(llm,qdrant_path or DATA_DIR / 'qdrant'), extract_transcript, str(DATA_DIR / 'checkpoints.db'))
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

class RecipeHandler(SimpleHTTPRequestHandler):
    """한입노트 JSON API와 허용된 정적 파일만 제공하는 HTTP 핸들러."""

    def send_json(self, status, body):
        """Python 값을 UTF-8 JSON HTTP 응답으로 전송한다.

        Args:
            status: HTTP 상태 코드 정수.
            body: ``json.dumps``로 직렬화 가능한 응답 값.

        Returns:
            반환값 없음. 상태·헤더·본문을 클라이언트 소켓에 쓴다.
        """
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        """상태·레시피·냉장고·작업 조회 또는 허용된 정적 파일을 처리한다.

        Returns:
            반환값 없음. 경로에 따라 JSON/정적 파일 응답을 직접 전송한다.

        Routes:
            ``/api/health`` 전체 준비 상태, ``/api/recipes`` 레시피 목록,
            ``/api/pantry`` 냉장고, ``/api/jobs/<id>`` 작업 상태,
            ``/api/status`` Ollama 모델 상태를 반환한다. 그 외에는 명시적으로
            허용한 UI 파일만 제공하고 내부 파일은 404로 차단한다.
        """
        route = self.path.split('?',1)[0]
        if route == '/api/health':
            self.send_json(200,service_health(STORE,pipelines().index)); return
        if route == '/api/recipes':
            self.send_json(200, {'recipes':[public(r) for r in STORE.all()]}); return
        if route == '/api/pantry':
            self.send_json(200, {'pantry':STORE.pantry()}); return
        if route.startswith('/api/jobs/'):
            job=STORE.job(route.rsplit('/',1)[1])
            self.send_json(200 if job else 404, job or {'error':'작업이 없습니다.'}); return
        if self.path.split("?", 1)[0] == "/api/status":
            base_url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
            model = os.environ.get("OLLAMA_MODEL", "gemma4:latest")
            try:
                request = Request(f"{base_url.rstrip('/')}/api/tags", headers={"User-Agent": "HanipNote"})
                with urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read().decode())
                names = [item.get("name") for item in payload.get("models", [])]
                installed=model in names or (':' not in model and model+':latest' in names)
                self.send_json(200, {"running": True, "model": model, "modelInstalled": installed, "models": names})
            except Exception:
                self.send_json(200, {"running": False, "model": model, "modelInstalled": False, "models": []})
            return
        # Never expose SQLite, checkpoints, source code or temporary audio via static serving.
        if route not in {'/','/index.html','/app.js','/styles.css','/assets/og.png'}:
            self.send_error(404); return
        super().do_GET()

    def do_HEAD(self):
        """HEAD 요청을 지원하지 않고 405 Method Not Allowed를 반환한다.

        Returns:
            반환값 없음. 오류 응답을 직접 전송한다.
        """
        self.send_error(405)

    def do_POST(self):
        """JSON 기반 변경·분석·검색 API 요청을 검증하고 라우팅한다.

        Returns:
            반환값 없음. 각 경로의 JSON 응답을 직접 전송한다.

        Routes:
            ``/api/analyze`` 작업 생성, ``/api/review`` 사용자 확인 재개,
            ``/api/retry`` 실패 작업 재시도, ``/api/pantry`` 냉장고 교체,
            ``/api/search`` 추천, ``/api/reindex`` 개별 재색인,
            ``/api/reindex-all`` 전체 재색인, ``/api/import`` 과거 브라우저
            레시피 이관을 처리한다.

        Error Responses:
            Content-Type 오류는 415, 입력·업무 규칙 오류는 422, 외부 연결
            오류는 502, 예상하지 못한 예외는 500 JSON으로 변환한다. 요청
            본문은 1바이트 이상 2MB 이하의 JSON 객체여야 한다.
        """
        try:
            if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                self.send_json(415,{'error':'application/json 요청만 지원합니다.'}); return
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 2_000_000: raise ValueError('요청 크기를 확인해 주세요.')
            body = json.loads(self.rfile.read(size).decode("utf-8"))
            if not isinstance(body,dict): raise ValueError('JSON 객체가 필요합니다.')
            if self.path == '/api/analyze':
                payload={'url':str(body.get('url','')).strip(),'text':str(body.get('text','')).strip()}
                id=str(uuid.uuid4()); STORE.job(id,status='queued',payload=payload)
                submit_job(id,payload)
                self.send_json(202,{'job_id':id}); return
            if self.path in {'/api/review','/api/retry'}:
                id=body['job_id']; job=STORE.job(id)
                if not job or job['status'] not in {'review','failed','running','queued'}: raise ValueError('재개할 작업이 없습니다.')
                if self.path == '/api/review' and job['status']!='review': raise ValueError('확인 대기 중인 작업이 아닙니다.')
                if self.path == '/api/retry' and job['status']=='review': raise ValueError('검토 내용을 확인해 주세요.')
                if self.path == '/api/review':
                    if body.get('approved') is not True: raise ValueError('확인 후 저장해 주세요.')
                    body['recipe']=normalize(body.get('recipe') or job['result']['recipe'])
                submit_job(id,resume=body if self.path=='/api/review' else None)
                self.send_json(202,{'job_id':id}); return
            if self.path == '/api/pantry':
                items=SearchInput(pantry=body.get('pantry',[])).pantry
                self.send_json(200,{'pantry':STORE.pantry(sorted({canonical(x) for x in items if x.strip()}))}); return
            if self.path == '/api/search':
                req=SearchInput.model_validate(body).model_dump()
                future=WORKER.submit(lambda:pipelines().search.invoke({'request':req})['result'])
                self.send_json(200,future.result()); return
            if self.path == '/api/reindex':
                future=WORKER.submit(lambda:pipelines().reindex(body['id']))
                self.send_json(200,future.result()); return
            if self.path == '/api/reindex-all':
                future=WORKER.submit(lambda:pipelines().reindex_all())
                self.send_json(200,future.result()); return
            if self.path == '/api/import':
                count=0; errors=[]
                for old in body.get('recipes',[]):
                    try:
                        r=normalize({'title':old['title'],'category':old.get('category','요리'),'time':old.get('time') or None,
                            'ingredients':[{'raw_name':x,'name':x} for x in old['ingredients']], 'steps':old['steps']})
                        key='legacy:'+str(old['id'])
                        STORE.save(str(uuid.uuid5(uuid.NAMESPACE_URL,key)),key,old.get('source',''),'',r,semantic(r,''),'legacy'); count+=1
                    except (ValueError,KeyError,TypeError) as e: errors.append(str(e))
                self.send_json(200,{'imported':count,'errors':errors}); return
            self.send_json(404,{'error':'Not found'})
        except (ValueError, RuntimeError, KeyError, TypeError) as error:
            self.send_json(422, {"error": str(error)})
        except (HTTPError, URLError, TimeoutError) as error:
            self.send_json(502, {"error": "이 컴퓨터에서 YouTube 서버 연결이 차단됐어요. Ollama 문제가 아닙니다.", "detail": "인터넷 연결/프록시를 확인하거나, 자막 텍스트를 직접 입력하는 방식으로 테스트해 주세요. " + str(error)})
        except Exception as error:
            self.send_json(500, {"error": "분석 중 알 수 없는 오류가 발생했어요.", "detail": str(error)})

if __name__ == "__main__":
    host = os.environ.get('APP_HOST', '127.0.0.1')
    port = int(os.environ.get('APP_PORT', '8000'))
    httpd = ThreadingHTTPServer((host, port), RecipeHandler)
    display_host = 'localhost' if host in {'127.0.0.1','localhost'} else host
    print(f"한입노트가 http://{display_host}:{port} 에서 실행 중입니다.", flush=True)
    print("SQLite 원본 DB + LangGraph + 로컬 Ollama + Qdrant Local 검색 인덱스", flush=True)
    try: httpd.serve_forever()
    except KeyboardInterrupt: print("서버를 종료합니다.", flush=True)
    finally:
        httpd.server_close()
        WORKER.shutdown(wait=True)
        if PIPELINES:
            PIPELINES.checkpoint_db.close()
            PIPELINES.index.close()
