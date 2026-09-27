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
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from storage import Store, public
from integrations import Ollama, QdrantIndex
from workflows import Pipelines
from domain import normalize, semantic, canonical, SearchInput
from health import service_health

# This personal app must not send recipe/checkpoint content to cloud tracing services.
os.environ['LANGSMITH_TRACING'] = 'false'
os.environ['LANGCHAIN_TRACING_V2'] = 'false'

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
# Windows TEMP 권한 문제를 피하기 위해 앱 임시 파일을 전용 폴더에 만듭니다.
RUNTIME_DIR = ROOT / ".runtime"
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
    global PIPELINES
    if PIPELINES is None:
        llm = Ollama()
        PIPELINES = Pipelines(STORE, llm, QdrantIndex(llm,DATA_DIR / 'qdrant'), extract_transcript, str(DATA_DIR / 'checkpoints.db'))
    return PIPELINES

def submit_job(id, payload=None, resume=None):
    with ACTIVE_LOCK:
        if id in ACTIVE: raise ValueError('이미 처리 중인 작업입니다.')
        ACTIVE.add(id)
        STORE.job(id,status='queued')
    def work():
        try: pipelines().run(id,payload,resume)
        except Exception as e: STORE.job(id,status='failed',error=str(e))
        finally:
            with ACTIVE_LOCK: ACTIVE.discard(id)
    WORKER.submit(work)

def video_id_from_url(value):
    parsed = urlparse(value)
    if parsed.hostname in {"youtu.be", "www.youtu.be"}:
        return parsed.path.strip("/").split("/")[0]
    query_id = parse_qs(parsed.query).get("v", [None])[0]
    if query_id:
        return query_id
    match = re.search(r"(?:embed|shorts|live)/([\w-]{6,})", parsed.path)
    return match.group(1) if match else None

def transcript_from_youtube_transcript_api(video_id):
    """가벼운 자막 전용 라이브러리로 먼저 시도합니다."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from requests import Session
    except ImportError:
        raise RuntimeError("youtube-transcript-api가 설치되어 있지 않아요.")
    class TranscriptSession(Session):
        def request(self, *args, **kwargs):
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
    """자막이 없는 영상에서 오디오만 임시로 받아 로컬 Whisper로 변환합니다."""
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
    def send_json(self, status, body):
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
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
        self.send_error(405)

    def do_POST(self):
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
    httpd = ThreadingHTTPServer(("127.0.0.1", 8000), RecipeHandler)
    print("한입노트가 http://localhost:8000 에서 실행 중입니다.", flush=True)
    print("SQLite 원본 DB + LangGraph + 로컬 Ollama + Qdrant Local 검색 인덱스", flush=True)
    try: httpd.serve_forever()
    except KeyboardInterrupt: print("서버를 종료합니다.", flush=True)
    finally:
        httpd.server_close()
        WORKER.shutdown(wait=True)
        if PIPELINES:
            PIPELINES.checkpoint_db.close()
            PIPELINES.index.close()
