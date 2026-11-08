"""제한된 YouTube 메타데이터·미디어와 PyAV 프레임 추출 경계."""
import hashlib
import io
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

import requests

MAX_MEDIA_BYTES = 256 * 1024 * 1024
MAX_METADATA_BYTES = 6 * 1024 * 1024


class MetadataResponse(io.BytesIO):
    """크기가 제한된 본문과 urllib 메타데이터를 제공하는 메모리 응답."""

    def __init__(self, body, response):
        """검증된 bytes와 원래 응답 헤더를 복제한다. 추가 네트워크 요청은 없다."""
        super().__init__(body)
        self.headers = response.headers
        self.status = response.getcode()
        self.url = response.geturl()

    def info(self):
        """urllib 소비자가 요청한 헤더를 반환한다. 외부 상태를 변경하지 않는다."""
        return self.headers

    def getcode(self):
        """원래 HTTP 상태 코드를 반환한다. 외부 I/O는 없다."""
        return self.status

    def geturl(self):
        """검증된 마지막 응답 URL을 반환한다. 외부 I/O는 없다."""
        return self.url


class AnalysisBudget:
    """한 수집의 남은 활성 시간. 입력 seconds 후 check가 TimeoutError를 낸다."""

    def __init__(self, seconds=600, clock=time.monotonic):
        """양의 시간 예산과 단조 시계를 받아 마감 시점을 보관한다. 외부 I/O는 없다."""
        self.clock = clock
        self.deadline = clock() + seconds

    def remaining(self):
        """남은 초를 반환한다. 소진 시 0이며 외부 상태를 변경하지 않는다."""
        return max(0, self.deadline - self.clock())

    def check(self):
        """남은 시간을 반환하며 소진 시 TimeoutError를 발생시킨다."""
        remaining = self.remaining()
        if remaining <= 0:
            raise TimeoutError('분석 시간 한도에 도달해 수집을 중단했습니다.')
        return remaining


def validate_media_url(url):
    """HTTPS YouTube 호스트·공개 DNS만 허용한다. 잘못된 외부 주소는 ValueError다."""
    parsed = urlparse(url)
    host = parsed.hostname or ''
    allowed = any(host == suffix or host.endswith('.' + suffix)
                  for suffix in ('youtube.com', 'youtubei.googleapis.com', 'googlevideo.com', 'ytimg.com'))
    if (parsed.scheme != 'https' or not allowed or parsed.username or parsed.password
            or parsed.port not in {None, 443}):
        raise ValueError('허용되지 않은 영상 출처 주소입니다.')
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
        raise ValueError('사설 네트워크 영상 주소는 사용할 수 없습니다.')
    return url


def bounded_get(session, url, budget, *, limit, headers=None):
    """리다이렉트마다 검증하며 제한 이내 bytes를 반환한다. 초과·연결 오류는 전파한다."""
    for _ in range(5):
        validate_media_url(url)
        timeout = min(20, budget.check())
        with session.get(url, timeout=(min(5, timeout), timeout), stream=True,
                         allow_redirects=False, headers=headers) as response:
            if response.is_redirect:
                from urllib.parse import urljoin
                url = urljoin(url, response.headers.get('Location', ''))
                continue
            response.raise_for_status()
            if int(response.headers.get('Content-Length', '0')) > limit:
                raise ValueError('영상 응답 크기 제한을 넘었습니다.')
            data = bytearray()
            for chunk in response.iter_content(64 * 1024):
                budget.check()
                data.extend(chunk)
                if len(data) > limit:
                    raise ValueError('영상 응답 크기 제한을 넘었습니다.')
            return bytes(data)
    raise ValueError('영상 리다이렉트가 너무 많습니다.')


@dataclass(frozen=True)
class Frame:
    """실제 디코더 시점과 JPEG bytes. bytes는 체크포인트·DB에 넣지 않는다."""

    id: str
    time: float
    jpeg: bytes

    @property
    def digest(self):
        """판독 이미지 SHA256을 반환한다. 외부 쓰기는 없다."""
        return hashlib.sha256(self.jpeg).hexdigest()


def frame_times(duration, count=12):
    """시작·중간·끝을 포함한 최대 count 시점을 반환한다. 잘못된 길이는 ValueError다."""
    if not duration or duration <= 0:
        raise ValueError('영상 길이를 확인하지 못했습니다.')
    count = max(2, min(count, 24))
    return sorted({round((duration - min(0.5, duration / 10)) * index / (count - 1), 3)
                   for index in range(count)})


class MediaReader:
    """pytubefix 스트림 정보를 별도 프로세스에서 얻고 bytes·프레임을 제한한다."""

    def __init__(self, runtime_dir=None):
        """Whisper 캐시 경로를 보관한다. 디렉터리 생성·모델 설치는 하지 않는다."""
        from pathlib import Path
        self.runtime_dir = Path(runtime_dir or Path(__file__).resolve().parent / '.runtime')

    def resolve(self, video_id, budget):
        """ID의 메타데이터·스트림 URL을 반환한다. 자식 요청·프로세스에 마감 시간을 적용한다."""
        metadata = {}
        try:
            with requests.Session() as session:
                session.trust_env = False
                page = bounded_get(session, 'https://www.youtube.com/watch?v=' + video_id,
                    budget, limit=6 * 1024 * 1024,
                    headers={'User-Agent':'Mozilla/5.0'}).decode('utf-8')
            match = re.search(r'ytInitialPlayerResponse\s*=\s*', page)
            if match:
                player, _ = json.JSONDecoder().raw_decode(page[match.end():])
                details = player.get('videoDetails', {})
                metadata = {'title':details.get('title', ''), 'description':details.get('shortDescription', ''),
                            'duration':float(details['lengthSeconds']) if details.get('lengthSeconds') else None}
        except Exception:
            pass
        try:
            result = subprocess.run([sys.executable, '-X', 'utf8', str(__file__), '--resolve', video_id],
                capture_output=True, text=True, encoding='utf-8', timeout=min(90, budget.check()))
            if result.returncode:
                raise RuntimeError('영상 스트림을 확인하지 못했습니다.')
            resolved = json.loads(result.stdout)
            return {**resolved, **metadata}
        except Exception as error:
            if not metadata:
                raise RuntimeError('YouTube 메타데이터·영상 연결에 실패했습니다.') from error
            return {**metadata, 'warnings':['영상 스트림 연결 실패: ' + type(error).__name__]}

    def download(self, url, budget, limit=MAX_MEDIA_BYTES):
        """range 쿼리로 스트림을 제한 다운로드해 메모리 bytes를 반환한다. 파일은 만들지 않는다."""
        data = bytearray()
        chunk_size = 1024 * 1024
        with requests.Session() as session:
            session.trust_env = False
            for start in range(0, limit + 1, chunk_size):
                parsed = urlparse(url)
                query = [(key, value) for key, value in parse_qsl(parsed.query) if key != 'range']
                query.append(('range', f'{start}-{start + chunk_size - 1}'))
                part = bounded_get(session, urlunparse(parsed._replace(query=urlencode(query))), budget,
                                   limit=min(chunk_size, limit - len(data)) + 1)
                if len(data) + len(part) > limit:
                    raise ValueError('영상은 최대 256MiB까지 분석합니다.')
                data.extend(part)
                if len(part) < chunk_size:
                    break
            else:
                raise ValueError('영상은 최대 256MiB까지 분석합니다.')
        return bytes(data)

    def frames(self, metadata, times, budget):
        """영상 bytes에서 실제 타임스탬프의 JPEG 목록을 반환한다. 디코딩 실패는 전파한다."""
        import av
        if not metadata.get('video_url'):
            raise RuntimeError('화면을 읽을 영상 스트림이 없습니다.')
        media = self.download(metadata['video_url'], budget)
        result = []
        with av.open(io.BytesIO(media)) as container:
            stream = container.streams.video[0]
            for index, target in enumerate(times[:24]):
                budget.check()
                container.seek(int(target / stream.time_base), stream=stream, backward=True)
                for frame in container.decode(stream):
                    budget.check()
                    actual = float(frame.time or 0)
                    if actual + 0.02 < target:
                        continue
                    scale = min(1, 1280 / max(frame.width, frame.height))
                    width = max(2, int(frame.width * scale) // 2 * 2)
                    height = max(2, int(frame.height * scale) // 2 * 2)
                    frame = frame.reformat(width=width, height=height, format='yuvj420p')
                    encoder = av.CodecContext.create('mjpeg', 'w')
                    encoder.width = width; encoder.height = height
                    encoder.pix_fmt = 'yuvj420p'
                    from fractions import Fraction
                    encoder.time_base = Fraction(1, 25)
                    frame.pts = 0
                    jpeg = b''.join(bytes(packet) for packet in encoder.encode(frame))
                    jpeg += b''.join(bytes(packet) for packet in encoder.encode(None))
                    if not jpeg or len(jpeg) > 2 * 1024 * 1024:
                        raise ValueError('화면 이미지 크기 제한을 넘었습니다.')
                    result.append(Frame(f'frame:{index}', actual, jpeg))
                    break
        return result

    def speech(self, metadata, budget):
        """캐시된 Whisper로 오디오 bytes를 인식해 문자열을 반환한다.

        입력은 resolve 결과와 시간 예산이다. 자식 프로세스 제한으로 인식도
        마감 안에 종료한다. 캐시가 없으면 RuntimeError이며 모델 설치·파일 삭제는 없다.
        """
        cache = self.runtime_dir / 'whisper-models'
        if not cache.is_dir() or not metadata.get('audio_url'):
            raise RuntimeError('캐시된 Whisper 모델 또는 오디오 스트림이 없습니다.')
        media = self.download(metadata['audio_url'], budget)
        result = subprocess.run([sys.executable, '-X', 'utf8', str(__file__), '--speech',
            str(cache), os.getenv('WHISPER_MODEL', 'base')], input=media, capture_output=True,
            timeout=budget.check())
        if result.returncode:
            raise RuntimeError('캐시된 로컬 Whisper를 사용할 수 없습니다.')
        return json.loads(result.stdout.decode('utf-8'))['text']


def resolve_video(video_id):
    """자식 프로세스 전용 스트림 조회. 외부 요청을 허용 호스트·20초로 제한한다."""
    import re
    from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler
    from pytubefix import YouTube, request
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
        raise ValueError('잘못된 영상 ID입니다.')

    class CheckedRedirect(HTTPRedirectHandler):
        """리다이렉트 목적지를 검증하는 자식 전용 urllib 처리기."""

        def redirect_request(self, req, fp, code, msg, headers, newurl):
            """새 URL을 검사하고 urllib 원래 리다이렉트 요청을 반환한다."""
            validate_media_url(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = build_opener(ProxyHandler({}), CheckedRedirect())

    def checked_open(req, timeout=None):
        """pytubefix의 직접 요청을 검증 후 열고 응답 객체를 반환한다."""
        validate_media_url(req.full_url if hasattr(req, 'full_url') else req)
        with opener.open(req, timeout=20) as response:
            body = response.read(MAX_METADATA_BYTES + 1)
            if len(body) > MAX_METADATA_BYTES:
                raise ValueError('영상 정보 응답 크기 제한을 넘었습니다.')
            return MetadataResponse(body, response)

    request.urlopen = checked_open
    video = YouTube('https://www.youtube.com/watch?v=' + video_id,
                    use_oauth=False, allow_oauth_cache=False)
    metadata = {'title': video.title, 'duration': video.length, 'description': video.description or ''}
    streams = video.streams.filter(only_video=True, file_extension='mp4')
    stream = next((candidate for resolution in ('720p', '480p', '360p')
                   for candidate in streams if candidate.resolution == resolution), None)
    stream = stream or video.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
    audio = video.streams.get_audio_only()
    return {**metadata, 'video_url': stream.url if stream else None, 'audio_url':audio.url if audio else None}


def transcribe_cached(cache, model_name):
    """자식 프로세스에서 stdin 오디오를 기존 캐시로 인식한다. 네트워크 모델 설치는 없다."""
    from faster_whisper import WhisperModel
    media = sys.stdin.buffer.read(MAX_MEDIA_BYTES + 1)
    if len(media) > MAX_MEDIA_BYTES:
        raise ValueError('오디오 크기 제한을 넘었습니다.')
    model = WhisperModel(model_name, device='cpu', compute_type='int8',
                         download_root=cache, local_files_only=True)
    segments, _ = model.transcribe(io.BytesIO(media), language='ko', vad_filter=True)
    text = ' '.join(segment.text.strip() for segment in segments).strip()
    if not text:
        raise RuntimeError('인식할 음성이 없습니다.')
    return {'text':text}


if __name__ == '__main__':
    try:
        payload = (transcribe_cached(sys.argv[2], sys.argv[3]) if sys.argv[1] == '--speech'
                   else resolve_video(sys.argv[2]))
        print(json.dumps(payload, ensure_ascii=False))
    except Exception:
        raise SystemExit(1)
