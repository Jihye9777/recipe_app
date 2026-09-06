from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json
import os
import re
import tempfile

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
    # requests가 시스템 프록시 환경 변수를 따르지 않도록 합니다.
    http_client = Session()
    http_client.trust_env = False
    fetched = YouTubeTranscriptApi(http_client=http_client).fetch(video_id, languages=["ko", "en"])
    transcript = " ".join(item.text.strip() for item in fetched if item.text.strip()).strip()
    if not transcript:
        raise RuntimeError("youtube-transcript-api에서 빈 자막이 반환됐어요.")
    return transcript, fetched.language_code, f"YouTube 자막 · {fetched.language}"

def extract_transcript(video_url):
    video_id = video_id_from_url(video_url)
    if not video_id:
        raise ValueError("유효한 YouTube 주소를 입력해 주세요.")
    try:
        return transcript_from_youtube_transcript_api(video_id)
    except Exception as error:
        raise RuntimeError(f"자막 API로 자막을 가져오지 못했어요: {error}")

def call_ollama(transcript):
    schema = {"type": "object", "properties": {"title": {"type": "string"}, "category": {"type": "string"}, "time": {"type": "integer"}, "ingredients": {"type": "array", "items": {"type": "string"}}, "steps": {"type": "array", "items": {"type": "string"}}}, "required": ["title", "category", "time", "ingredients", "steps"]}
    prompt = "다음은 요리 영상의 자막입니다. 자막에 근거해서만 한국어 레시피를 JSON으로 정리하세요. 재료는 분량을 포함하고, 추측한 내용은 넣지 마세요. 조리 순서는 짧은 명령형 문장으로 작성하세요. JSON 키는 title, category, time, ingredients, steps만 사용하세요.\n\n" + transcript[:18000]
    base_url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
    model = os.environ.get("OLLAMA_MODEL", "gemma4:latest")
    payload = {"model": model, "prompt": prompt, "format": schema, "stream": False, "options": {"temperature": 0.2}}
    request = Request(f"{base_url.rstrip('/')}/api/generate", data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=120) as response:
        result = json.loads(response.read().decode())
    if not result.get("response"):
        raise RuntimeError("Ollama 응답이 비어 있어요.")
    return json.loads(result["response"])

def call_available_model(transcript):
    try:
        return call_ollama(transcript), "Ollama · " + os.environ.get("OLLAMA_MODEL", "gemma4:latest")
    except (URLError, TimeoutError, HTTPError, json.JSONDecodeError):
        return None, None

class RecipeHandler(SimpleHTTPRequestHandler):
    def send_json(self, status, body):
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/api/status":
            base_url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
            model = os.environ.get("OLLAMA_MODEL", "gemma4:latest")
            try:
                request = Request(f"{base_url.rstrip('/')}/api/tags", headers={"User-Agent": "HanipNote"})
                with urlopen(request, timeout=2) as response:
                    payload = json.loads(response.read().decode())
                names = [item.get("name") for item in payload.get("models", [])]
                self.send_json(200, {"running": True, "model": model, "modelInstalled": model in names, "models": names})
            except Exception:
                self.send_json(200, {"running": False, "model": model, "modelInstalled": False, "models": []})
            return
        super().do_GET()

    def do_POST(self):
        if self.path != "/api/analyze":
            self.send_json(404, {"error": "Not found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(size).decode("utf-8"))
            video_url = body.get("url", "").strip()
            pasted_text = body.get("text", "").strip()
            if pasted_text:
                transcript, language, source = pasted_text, "직접 입력", "직접 붙여넣은 텍스트"
                video_id = None
            else:
                video_id = video_id_from_url(video_url)
                if not video_id:
                    raise ValueError("유효한 YouTube 주소를 입력하거나 자막 텍스트를 붙여 넣어 주세요.")
                transcript, language, source = extract_transcript(video_url)
            recipe, provider = call_available_model(transcript)
            self.send_json(200, {"videoId": video_id, "language": language, "source": source, "transcriptChars": len(transcript), "recipe": recipe, "aiEnabled": bool(provider), "provider": provider})
        except (ValueError, RuntimeError) as error:
            self.send_json(422, {"error": str(error)})
        except (HTTPError, URLError, TimeoutError) as error:
            self.send_json(502, {"error": "이 컴퓨터에서 YouTube 서버 연결이 차단됐어요. Ollama 문제가 아닙니다.", "detail": "인터넷 연결/프록시를 확인하거나, 자막 텍스트를 직접 입력하는 방식으로 테스트해 주세요. " + str(error)})
        except Exception as error:
            self.send_json(500, {"error": "분석 중 알 수 없는 오류가 발생했어요.", "detail": str(error)})

if __name__ == "__main__":
    print("한입노트가 http://localhost:8000 에서 실행 중입니다.", flush=True)
    print("항상 로컬 Ollama 모델을 사용합니다.", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8000), RecipeHandler).serve_forever()
