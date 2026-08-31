from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from xml.etree import ElementTree
import html
import json
import os
import re
import ssl
import time

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

def video_id_from_url(value):
    parsed = urlparse(value)
    if parsed.hostname in {"youtu.be", "www.youtu.be"}:
        return parsed.path.strip("/").split("/")[0]
    query_id = parse_qs(parsed.query).get("v", [None])[0]
    if query_id:
        return query_id
    match = re.search(r"(?:embed|shorts|live)/([\w-]{6,})", parsed.path)
    return match.group(1) if match else None

def get_url(url, timeout=18):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (HanipNote recipe parser)"})
    with urlopen(request, timeout=timeout, context=ssl._create_unverified_context()) as response:
        return response.read()

def transcript_for(video_id):
    page = get_url(f"https://www.youtube.com/watch?v={video_id}").decode("utf-8", "ignore")
    marker = '"captionTracks":'
    start = page.find(marker)
    if start < 0:
        raise RuntimeError("이 영상에서 자막을 찾지 못했어요. 자막이 켜진 영상을 사용해 주세요.")
    start = page.find("[", start + len(marker))
    tracks, _ = json.JSONDecoder().raw_decode(page[start:])
    tracks.sort(key=lambda item: 0 if item.get("languageCode") == "ko" else (1 if item.get("languageCode") == "en" else 2))
    selected = tracks[0]
    xml_data = get_url(selected["baseUrl"] + "&fmt=srv3")
    root = ElementTree.fromstring(xml_data)
    lines = []
    for node in root.findall(".//text"):
        value = " ".join("".join(node.itertext()).split())
        if value:
            lines.append(html.unescape(value))
    return " ".join(lines), selected.get("languageCode", "unknown")

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

    def do_POST(self):
        if self.path != "/api/analyze":
            self.send_json(404, {"error": "Not found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(size).decode("utf-8"))
            video_url = body.get("url", "")
            video_id = video_id_from_url(video_url)
            if not video_id:
                raise ValueError("유효한 YouTube 주소를 입력해 주세요.")
            transcript, language = transcript_for(video_id)
            recipe, provider = call_available_model(transcript)
            self.send_json(200, {"videoId": video_id, "language": language, "transcriptChars": len(transcript), "recipe": recipe, "aiEnabled": bool(provider), "provider": provider})
        except (ValueError, RuntimeError) as error:
            self.send_json(422, {"error": str(error)})
        except (HTTPError, URLError, TimeoutError) as error:
            self.send_json(502, {"error": "이 컴퓨터에서 YouTube 서버 연결이 차단됐어요. Ollama 문제가 아닙니다.", "detail": "인터넷 연결/프록시를 확인하거나, 자막 텍스트를 직접 입력하는 방식으로 테스트해 주세요. " + str(error)})
        except Exception as error:
            self.send_json(500, {"error": "분석 중 알 수 없는 오류가 발생했어요.", "detail": str(error)})

print("한입노트가 http://localhost:8000 에서 실행 중입니다.", flush=True)
print("항상 로컬 Ollama 모델을 사용합니다.", flush=True)
ThreadingHTTPServer(("127.0.0.1", 8000), RecipeHandler).serve_forever()
