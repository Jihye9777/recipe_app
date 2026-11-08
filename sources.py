"""자막 성공 여부와 별개로 설명란·시간별 화면 글씨를 수집한다."""
import requests
from evidence import Source, SourceBundle, PartialFrameReadError
from media_sources import MediaReader, AnalysisBudget, frame_times, validate_media_url


def captions(video_id, *, budget=None):
    """자막 API 조각을 시점·언어·생성 여부가 있는 출처 목록으로 반환한다. 오류는 전파한다."""
    from youtube_transcript_api import YouTubeTranscriptApi
    budget = budget or AnalysisBudget()
    with requests.Session() as session:
        session.trust_env = False
        # requests는 connect/read 중 각각 최대 20초 대기한다.
        original_request = session.request

        def timed_request(method, url, **kwargs):
            """자막 API 요청을 유한 timeout으로 전송하고 응답을 반환한다."""
            validate_media_url(url)
            remaining = min(20, budget.check())
            kwargs.update(timeout=(min(5, remaining), remaining), stream=True, allow_redirects=False)
            response = original_request(method, url, **kwargs)
            try:
                if response.is_redirect:
                    raise RuntimeError('자막 요청 리다이렉트를 허용하지 않습니다.')
                data = bytearray()
                for chunk in response.iter_content(64 * 1024):
                    budget.check()
                    data.extend(chunk)
                    if len(data) > 2 * 1024 * 1024:
                        raise ValueError('자막 응답 크기 제한을 넘었습니다.')
                response._content = bytes(data)
                response._content_consumed = True
                return response
            finally:
                response.close()

        session.request = timed_request
        fetched = YouTubeTranscriptApi(http_client=session).fetch(video_id, languages=['ko', 'en'])
    return [Source(id=f'caption:{index}', kind='caption', text=part.text,
                   start=part.start, end=part.start + part.duration,
                   language=fetched.language_code, generated=fetched.is_generated)
            for index, part in enumerate(fetched) if part.text.strip()]


class EvidenceCollector:
    """수집 의존성을 주입받아 보존형 출처 묶음을 만든다. 자동 설치·다운로드 캐시는 없다."""

    def __init__(self, llm, *, reader=None, fetch_captions=captions):
        """로컬 모델·미디어·자막 수집 의존성을 보관한다. 외부 I/O는 없다."""
        self.llm = llm
        self.reader = reader or MediaReader()
        self.fetch_captions = fetch_captions

    def collect(self, video_id, *, report=None):
        """영상 ID를 최대 600초·12화면으로 수집해 SourceBundle을 반환한다.

        실패한 채널은 경고로 남긴다. 어느 채널에도 유효 텍스트가 없으면
        RuntimeError다. 이미지 판독 결과는 모델 관찰이며 검토 대상으로 남긴다.
        """
        budget = AnalysisBudget()
        bundle = SourceBundle(video_id=video_id)

        def stage(name):
            """선택 작업 콜백으로 현재 단계명을 전달한다. 원문은 전달하지 않는다."""
            budget.check()
            if report:
                report(name)

        stage('collect_captions')
        try:
            bundle.sources.extend(self.fetch_captions(video_id, budget=budget))
        except Exception as error:
            bundle.warnings.append('자막 수집 실패: ' + type(error).__name__)
        try:
            stage('collect_description')
            metadata = self.reader.resolve(video_id, budget)
            bundle.warnings.extend(metadata.get('warnings', []))
            bundle.title = metadata.get('title', '')
            bundle.duration_seconds = metadata.get('duration') or None
            bundle.sources.append(Source(id='description', kind='description',
                                         text=metadata.get('description', '')[:60000]))
        except Exception as error:
            metadata = {}
            bundle.warnings.append('설명란·영상 정보 수집 실패: ' + type(error).__name__)
        if not any(source.kind == 'caption' for source in bundle.sources) and metadata:
            try:
                stage('collect_speech')
                text = self.reader.speech(metadata, budget)
                bundle.sources.append(Source(id='speech:0', kind='speech', text=text, language='ko'))
            except Exception as error:
                bundle.warnings.append('로컬 음성 인식 실패: ' + type(error).__name__)
        if metadata:
            try:
                stage('collect_frames')
                frames = self.reader.frames(metadata, frame_times(bundle.duration_seconds), budget)
                if not frames:
                    raise RuntimeError('디코딩된 화면이 없습니다.')
                bundle.coverage = {'method': 'uniform_sample', 'requested_frames': 12,
                    'decoded_frames': len(frames), 'read_frames': 0,
                    'times': [frame.time for frame in frames], 'whole_video_verified': False}
                stage('inspect_frames')
                try:
                    observations = self.llm.inspect_frames(frames, deadline=budget.deadline)
                except PartialFrameReadError as error:
                    observations = error.sources
                    bundle.warnings.append(str(error))
                frame_map = {frame.id:frame for frame in frames}
                checked = []
                for source in observations:
                    source = Source.model_validate(source)
                    frame_id = source.id.removesuffix(':action')
                    frame = frame_map.get(frame_id)
                    if (not frame or source.start != frame.time or source.end != frame.time
                            or source.kind not in {'screen_text', 'visual_action'}):
                        raise ValueError('화면 관찰의 실제 출처·시점이 다릅니다.')
                    checked.append(source.model_copy(update={'frame_hash':frame.digest}))
                bundle.sources.extend(checked)
                bundle.coverage['read_frames'] = len({source.id for source in checked
                                                       if source.kind == 'screen_text'})
                bundle.warnings.append('간격별 화면 판독 초안입니다. 화면 글씨·조리 순서를 원본과 확인해 주세요.')
            except Exception as error:
                bundle.warnings.append('화면 수집·판독 실패: ' + type(error).__name__)
        if not bundle.coverage:
            bundle.coverage = {'method': 'unavailable', 'decoded_frames': 0, 'whole_video_verified': False}
            bundle.warnings.append('화면 정보를 확보하지 못해 재료·조리 단계 누락 가능성이 있습니다.')
        if not any(source.text.strip() for source in bundle.sources):
            raise RuntimeError('자막·설명란·화면에서 사용할 자료를 확보하지 못했습니다.')
        return bundle
