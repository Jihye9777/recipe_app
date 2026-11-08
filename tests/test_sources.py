"""수집 채널을 합성 대역으로 바꿔 누락·실패·자원 한도를 검증한다."""
import time
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from evidence import Source
from sources import EvidenceCollector
from media_sources import Frame, AnalysisBudget, bounded_get, frame_times
from integrations import Ollama
from media_sources import resolve_video


class SourceTests(unittest.TestCase):
    """자막 성공도 설명란·화면 수집을 생략하지 않는다."""

    def collector(self, readings=None):
        """합성 메타데이터·화면·판독 수집기를 반환한다. 실제 네트워크는 쓰지 않는다."""
        reader = Mock()
        reader.resolve.return_value = {'title':'합성', 'duration':20, 'description':'마늘 1개'}
        reader.frames.return_value = [Frame('frame:0', 2, b'jpeg')]
        llm = Mock()
        llm.inspect_frames.return_value = readings or [Source(id='frame:0', kind='screen_text',
                                                            text='마늘을 가열해요', start=2, end=2)]
        collector = EvidenceCollector(llm, reader=reader, fetch_captions=lambda _, **kwargs: [Source(
            id='caption:0', kind='caption', text='음악', start=0, end=1)])
        return collector

    def test_caption_success_still_collects_description_and_screen(self):
        """모든 채널의 출처를 보존하고 모델 화면 판독은 계속 검토 대상으로 남긴다."""
        collector = self.collector()
        bundle = collector.collect('gcwOptvjdgA')
        self.assertEqual({s.kind for s in bundle.sources}, {'caption','description','screen_text'})
        self.assertTrue(bundle.warnings)
        self.assertFalse(bundle.coverage['whole_video_verified'])

    def test_invented_frame_id_or_time_is_rejected(self):
        """주지 않은 화면·시점을 관찰 출처로 저장하지 않는다."""
        for source in [Source(id='frame:invented', kind='screen_text', text='마늘', start=2, end=2),
                       Source(id='frame:0', kind='screen_text', text='마늘', start=99, end=99)]:
            bundle = self.collector([source]).collect('gcwOptvjdgA')
            self.assertFalse(any(s.kind == 'screen_text' for s in bundle.sources))
            self.assertTrue(any('실패' in issue for issue in bundle.warnings))

    def test_screen_failure_keeps_caption_and_description(self):
        """디코더·모델 실패에도 수집한 원문과 실패 사유를 보존한다."""
        collector = self.collector()
        collector.reader.frames.side_effect = ImportError('decoder unavailable')
        bundle = collector.collect('gcwOptvjdgA')
        self.assertEqual(len(bundle.sources), 2)
        self.assertEqual(bundle.coverage['method'], 'unavailable')

    def test_invalid_media_redirect_and_oversize_are_rejected(self):
        """사설 목적지·과대 응답이 미디어 경계를 통과하지 못한다."""
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.is_redirect = True
        response.headers = {'Location':'http://127.0.0.1/private'}
        session = Mock()
        session.get.return_value = response
        dns = [(2,1,6,'',('8.8.8.8',443))]
        with patch('media_sources.socket.getaddrinfo', return_value=dns):
            with self.assertRaises(ValueError):
                bounded_get(session, 'https://www.youtube.com/watch', AnalysisBudget(), limit=10)
            response.is_redirect = False
            response.headers = {'Content-Length':'20'}
            with self.assertRaises(ValueError):
                bounded_get(session, 'https://www.youtube.com/watch', AnalysisBudget(), limit=10)

    def test_expired_budget_stops_and_frames_cover_start_end(self):
        """가짜 시계로 시간 한도를 확인하고 전체 구간 탐색 시점을 검증한다."""
        clock = Mock(side_effect=[0, 11])
        with self.assertRaises(TimeoutError):
            AnalysisBudget(10, clock).check()
        times = frame_times(20)
        self.assertEqual(len(times), 12)
        self.assertEqual(times[0], 0)
        self.assertGreater(times[-1], 19)

    def test_vision_rejects_invented_frame_reference(self):
        """Ollama의 외부 JSON 응답에 허위 ID가 있으면 ValueError다."""
        llm = Ollama()
        llm.post = Mock(side_effect=[{'capabilities':['vision']}, {'response':
            '{"readings":[{"frame_id":"fake","text":"우유","action":"","readable":true}]}'}])
        with self.assertRaises(ValueError):
            llm.inspect_frames([Frame('frame:0', 3, b'jpeg')], deadline=time.monotonic() + 10)

    def test_late_vision_failure_preserves_successful_batches(self):
        """뒤 배치의 시간 초과도 앞 판독과 실제 디코딩 범위를 지우지 않는다."""
        collector = self.collector()
        collector.reader.frames.return_value = [Frame(f'frame:{i}', i, b'jpeg') for i in range(5)]
        collector.llm = Ollama()
        readings = [{'frame_id': f'frame:{i}', 'text': '마늘', 'action': '', 'readable': True}
                    for i in range(4)]
        collector.llm.post = Mock(side_effect=[{'capabilities': ['vision']},
            {'response': json.dumps({'readings': readings})}, TimeoutError('late batch')])
        bundle = collector.collect('gcwOptvjdgA')
        self.assertEqual(len([source for source in bundle.sources if source.kind == 'screen_text']), 4)
        self.assertEqual(bundle.coverage['decoded_frames'], 5)
        self.assertEqual(bundle.coverage['read_frames'], 4)
        self.assertTrue(any('일부' in warning for warning in bundle.warnings))

    def test_child_resolver_rejects_oversize_response(self):
        """pytubefix 내부 read도 메타데이터 크기 제한을 우회하지 못한다."""
        import pytubefix.request
        response = io.BytesIO(b'x' * (6 * 1024 * 1024 + 1))
        response.headers = {}
        opener = Mock()
        opener.open.return_value = response
        video = SimpleNamespace(title='합성', length=15, description='', streams=Mock())
        video.streams.filter.return_value = [SimpleNamespace(resolution='720p', url='https://example.invalid')]

        def create_video(*args, **kwargs):
            """실제 후킹된 urllib 호출로 합성 응답을 읽는다."""
            pytubefix.request.urlopen('https://www.youtube.com/watch?v=gcwOptvjdgA').read()
            return video

        dns = [(2, 1, 6, '', ('8.8.8.8', 443))]
        with patch('urllib.request.build_opener', return_value=opener), \
                patch('pytubefix.YouTube', side_effect=create_video), \
                patch('pytubefix.request.urlopen'), \
                patch('media_sources.socket.getaddrinfo', return_value=dns):
            with self.assertRaisesRegex(ValueError, '크기'):
                resolve_video('gcwOptvjdgA')
