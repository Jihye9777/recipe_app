# Adaptive recipe evidence implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 자막·설명란과 간격별 화면을 수집하고 필요한 구간을 보완해, 근거가 있는 조리 정보를 보존하고 예상 대기시간을 안내한다.

**Architecture:** 출처 수집과 미디어 처리는 새 어댑터로 분리한다. LangGraph가 버전형 출처 묶음·고정 사실·품질 검사·검토·저장을 연결한다. 기존 SQLite 원본과 Qdrant 검색 흐름은 유지한다.

**Tech Stack:** 기존 Python, FastAPI, LangGraph, SQLite, Ollama, youtube-transcript-api, pytubefix 11.1.0, faster-whisper 1.2.1, 설치된 PyAV 18.1.0.

**Spec:** `docs/superpowers/specs/2026-10-28-adaptive-recipe-evidence-design.md`.

## Global constraints

- 1분 안팎은 성능 목표이며 보장 시간이 아니다. 1분이 지나도 추가 확인을 계속한다.
- 최초 탐색 최대 12프레임, 추가 확인 최대 2회, 전체 이미지 분석 최대 24프레임, 실제 분석 시간 기본 상한 600초. 대기열·사용자 검토 대기는 분석 예산에 포함하지 않는다.
- 영상 전체 검증 완료라는 상태를 두지 않는다. 모든 누락의 제거나 모든 영상의 완전한 이해를 보장하지 않는다.
- 기존 FastAPI·LangGraph·SQLite·Qdrant Local·Ollama와 직접 텍스트 입력을 유지한다.
- 유료 API·클라우드 추적·yt-dlp는 추가하지 않는다. 모델·패키지를 자동 설치하지 않는다.
- 기존 레시피의 자동 교체는 범위 밖이다. 기존 데이터·인덱스·체크포인트를 초기화하지 않는다.
- `.env`, `.env.*`, `credentials/`, CONTEXT 이력은 읽지 않는다. 예시는 공개 `.env.example`에만 추가한다.
- 기존 서버를 종료·재시작하지 않는다. 새 평가 결과는 격리된 경로에 남기고 임시 미디어도 삭제 승인 없이 자동 삭제하지 않는다.
- 문서·함수 계약은 한국어로 작성하고 외부 입력 검증·HTML 이스케이프·SQL 바인딩을 유지한다.
- 이 계획과 설계는 제품 구현 전 사용자 확인 대상이다. 원격 push·PR·추가 병합은 포함하지 않는다.

## 확인한 환경과 실행 방식 제안

2026-10-28 읽기 전용 확인에서 Ollama는 `gemma4:latest`의 vision 기능을 보고했다. `av`, pytubefix, faster-whisper가 설치돼 있다. 외부 ffmpeg·ffprobe 명령은 찾지 못했다. 이것은 실제 프레임 판독·속도 검증 결과가 아니다.

실행은 Native를 추천한다. 아래 여섯 작업은 SourceBundle과 승인·시간 예산 계약을 공유하므로 한 구현자가 순서대로 연결하고 마지막에 독립 검토를 받는 편이 인터페이스 변경을 관리하기 쉽다. 사용자 선택 전에는 실행하지 않는다.

## Review focus

1. 영상 다운로드의 리다이렉트·과대 응답·사설 주소가 설명란/영상 수집을 통해 안전 경계를 우회하지 않아야 한다. 작업 1·2의 경계 테스트로 고정한다.
2. 화면에서 읽은 값이나 모델 묘사가 실제 자막 인용으로 둔갑하지 않아야 한다. 작업 3·4의 출처 검증 테스트로 고정한다.
3. 재시도·검토 재개·서버 재시작이 예산·취소를 초기화하거나 오래된 승인을 다른 근거에 적용하지 않아야 한다. 작업 4·5에서 검사한다.
4. 음성 없는 요리 영상, 짧게 지나가는 글씨, 설명란만 있는 재료가 수집 성공이라는 이유로 누락 없이 분석됐다고 표시되면 안 된다. 작업 2·3·4의 샘플 제한·검토 테스트로 고정한다.
5. 기존 URL과 직접 텍스트 입력이 영상 수집·덮어쓰기·잘못된 ETA에 휘말리지 않아야 한다. 작업 4·5의 API·DOM 테스트로 고정한다.

## 파일 책임과 공통 인터페이스

- `evidence.py`를 새로 만든다. `Source`, `Observation`, `SourceBundle` Pydantic 타입과 출처 검증·충돌·수집 범위 검사를 맡는다. `domain.py`는 이 타입을 가져와 재료/단계의 근거 ID와 불 세기 필드를 추가한다.
- `sources.py`를 새로 만든다. `EvidenceCollector.collect(video_id, budget, report) -> SourceBundle`, `refine(bundle, candidates, budget, report) -> SourceBundle`를 제공한다. 새 revision을 반환하고 입력 묶음은 수정하지 않는다.
- `media_sources.py`를 새로 만든다. `MediaReader.frames(video_id, times, budget) -> list[Frame]`, `speech(video_id, start, end, budget) -> Source`를 제공한다. URL·용량·시간 제한과 PyAV 디코딩을 이 경계에 모은다.
- `progress.py`를 새로 만든다. `AnalysisBudget`이 600초 활성 실행 예산과 취소를 관리한다. `estimate_remaining(history, workload) -> tuple[float, float] | None`는 개인 원문 없이 예상 범위를 반환한다.
- `integrations.py`는 `Ollama.inspect_frames(frames, *, deadline) -> list[Observation]`과 출처 묶음 구조화 호출을 추가한다. 기존 직접 텍스트 호출은 유지한다.
- `storage.py`는 `recipes.sources`, `jobs.progress` JSON과 별도 `jobs.cancel_requested` 열을 보존형 추가한다. 시간 통계는 `analysis_metrics` 테이블에 원문 없이 저장한다.
- `workflows.py`가 수집·보완·검사·저장 순서와 출처 revision 승인 해시를 소유한다. `server.py`는 생성·조회·취소·실행 버전 API를 연결한다.
- `app.js`, `api_schemas.py`, `README.md`가 새로운 진행·출처 표시와 사용 방법을 반영한다. 기존 삭제·검색·검토 기능은 유지한다.

### Task 1: 출처 모델과 보존형 저장 계약

**Files:** Create `evidence.py`, `tests/test_evidence.py`; modify `domain.py`, `storage.py`; extend `tests/test_workflows.py`.

**Interfaces:** `SourceBundle(version='recipe-sources-v2', revision, video_id, title, duration_seconds, sources, observations, warnings, coverage)`를 JSON 직렬화한다. `Source`는 id/kind/text/start/end/language/generated/status를 갖는다. `Observation`은 출처 ID와 종류·인용·시점·판독 여부를 갖는다. 영상/이미지 base64는 이 모델에 넣지 않는다. `Store.save(..., *, sources=None)`는 기존 호출을 유지한다.

- [ ] 실패 테스트를 쓴다. `test_source_id_and_time_must_exist`는 알 수 없는 출처와 음수·역전 구간을 거부한다. `test_visual_action_is_not_literal_caption`는 이미지 관찰을 자막 문자열 일치로 승인하지 않는다.
- [ ] 실패 테스트를 실행한다. `.\.venv-graph\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_evidence.py -v`는 구현 전 ImportError/기대 동작 실패여야 한다.
- [ ] 모델과 저장 변경을 구현한다. `CookingStep`에는 `heat: str | None`, `source_ids: list[str]`를 기본값과 함께 추가한다. 재료·사실의 근거 ID도 보존한다. 기존 `steps`는 유지한다. SQLite 열 기본값은 빈 JSON이며 이전 행을 다시 쓰지 않는다. 취소 플래그는 진행 JSON과 별도 SQL 갱신해 경쟁 쓰기에 유실되지 않게 한다.
- [ ] `test_migration_preserves_original_recipe`로 이전 DB 행의 JSON·원문 해시 불변과 두 번 초기화의 동일 결과를 검사한다. 과거 필드 없는 JSON도 읽는다. 작업 1 테스트 및 기존 Python 전체가 통과해야 한다.
- [ ] 관련 파일만 커밋한다. 메시지는 `feat: 출처 근거 모델과 보존형 저장 구조 추가`.

### Task 2: 시간·주소·용량이 제한된 자막·설명란·미디어 수집

**Files:** Create `sources.py`, `media_sources.py`, `progress.py`, `tests/test_sources.py`, `tests/test_media_sources.py`; modify `server.py` 수집 연결, `requirements-graph.txt`와 검증 가능한 lock의 PyAV 직접 사용 선언.

**Interfaces:** `AnalysisBudget(remaining_seconds, cancel_check, clock)`와 `remaining()/check()`를 사용한다. `Frame`은 index/start/end/이미지 bytes를 메모리에만 갖고 JSON 출처에는 파일 참조·시점·해시만 남긴다. 수집 콜백 `report(stage, reason, completed, total)`는 진행 정보만 전달한다.

- [ ] `test_caption_success_still_collects_description`, `test_private_redirect_rejected`, `test_oversize_stream_stops`, `test_missing_decoder_is_warning`, `test_music_does_not_trigger_repeated_speech` 실패 테스트를 쓴 뒤 두 새 파일 대상으로 실행한다.
- [ ] 자막 조각의 언어·자동 생성·시점을 보존하고 설명란을 추가한다. 빈 설명란과 요청 실패를 구별한다. HTTPS YouTube/YouTube 이미지·미디어 호스트만 허용하고 IP·DNS 결과·각 리다이렉트를 검증한다. 설명란 링크를 열지 않는다. 네트워크 read timeout은 남은 예산과 20초 중 작은 값으로 제한한다.
- [ ] pytubefix로 스트림 정보를 얻되 무제한 다운로드 함수를 호출하지 않는다. 검증한 스트림을 최대 256MiB까지 청크 단위로 전용 작업 경로에 내려받고 예산·취소를 확인한다. 요청 라이브러리의 숨은 네트워크도 같은 정책을 적용할 수 없는 경로는 사용하지 않는다.
- [ ] PyAV로 디코딩한다. 프레임 긴 변은 최대 1280px, 한 이미지 2MiB, 최초 12개, 총 24개를 넘지 않는다. 배열·JPEG 인코딩은 설치된 PyAV 기능을 사용하며 새 Pillow 설치를 전제하지 않는다. 시작·중간·끝을 포함하고 중복 시점은 제거한다.
- [ ] 추가 음성 구간은 최대 30초씩, 합계 120초로 제한한다. 설치된 Whisper 모델 캐시가 없으면 다운로드 대신 경고한다. 음악·음성 없음은 수집 상태로 남긴다. 미디어 파일 자동 삭제는 구현하지 않는다. 이 제한은 전체 600초 상한보다 우선하지 않는다.
- [ ] 가짜 스트림/프레임/시계로 용량·타임아웃·취소·부분 결과 보존을 검증하고 작업 2 테스트를 통과시킨다. 실제 영상 다운로드는 이 작업 단위 테스트에 포함하지 않는다.
- [ ] 관련 파일을 `feat: 설명란과 제한된 영상 음성 수집 추가`로 커밋한다.

### Task 3: 이미지 관찰과 추가 구간 선택

**Files:** Modify `integrations.py`, `sources.py`, `prompts/recipe.md`; create `tests/test_adaptive_sources.py`; extend `tests/test_recipe_prompt.py`.

**Interfaces:** `inspect_frames`는 실제 주어진 Frame ID만 참조한 Observation을 반환한다. `choose_candidates(bundle, limit=2) -> list[tuple[float,float]]`는 실수 영상 구간을 반환한다. `refine`는 최대 2회 보완하며 새 SourceBundle revision을 만든다.

- [ ] `test_invented_frame_reference_rejected`, `test_unknown_visual_identity_requires_review`, `test_untimed_description_uses_broad_probe`, `test_refinement_never_exceeds_24_frames`를 작성해 먼저 실패시킨다.
- [ ] `/api/show`로 vision 지원 여부를 확인하고 `/api/generate`의 images와 구조 스키마로 관찰한다. 요청 timeout은 남은 예산과 180초 중 작은 값이다. OCR 인용과 시각 동작을 구분하고 잘린 글씨·형태만으로 수량·불 세기를 추정하지 못하게 한다.
- [ ] 설명란 재료 불대응·조리 동작 희박·판독 불가·분량 충돌을 후보 신호로 구현한다. 시점 있는 경고 구간을 우선하고 시점 없는 정보는 확보한 탐색 화면의 대응 또는 가장 큰 미확인 간격을 사용한다. 임의 시점을 모델이 만들어내게 하지 않는다. 동일 구간 반복은 제거한다.
- [ ] 원문 텍스트/음성·프레임 관찰을 출처별로 유지한다. 보완 실패 경고는 repair로 지우지 않는다. 문서에 나온 다른 요리·선택 재료를 무조건 필수 재료로 넣지 않는다. 음악뿐인 원문을 두 번 보완하지 않는 테스트를 포함한다.
- [ ] 새 테스트와 기존 프롬프트 테스트를 실행해 통과시킨다. 실제 모델 정확도는 여기서 주장하지 않는다.
- [ ] `feat: 화면 근거와 선택적 구간 보완 연결`로 커밋한다.

### Task 4: LangGraph 출처 검사·승인·중단 연결

**Files:** Modify `workflows.py`, `recipe_quality.py`, `domain.py`; create `tests/test_evidence_workflow.py`; extend `tests/test_step_workflow.py`, `tests/test_step_quality.py`.

**Interfaces:** 수집 → 초기 사실 → 보완 후보 검사 → 제한 보완 → 최종 고정 사실 → 레시피 구조화 → 원문 대조 → 검토/저장 순서다. `quality(..., source_bundle=None)`는 레거시 호출을 유지한다. `approval_hash(recipe, bundle_revision)`가 승인 대상을 묶는다. State에 출처 묶음·사실 revision·보완 횟수·예산 잔여를 보존한다.

- [ ] `test_description_only_ingredient_cannot_silently_disappear`, `test_changed_evidence_invalidates_approval`, `test_visual_action_stays_review`, `test_legacy_checkpoint_cannot_auto_save`, `test_manual_text_never_downloads_video`, `test_duplicate_keeps_existing_row`를 작성해 실패를 확인한다.
- [ ] 기존 단일 텍스트 검사만 호출하는 우회를 막고 각 재료·단계의 실제 출처 ID·인용·시간·기구·불 세기를 대조한다. 부족한 입력을 모델 상식으로 채운 결과는 검토로 보낸다. 출처 revision이 바뀌면 새 사실 스냅샷을 추가하고 기존 스냅샷은 보존한다.
- [ ] 예산과 취소는 단계 시작 전 및 외부 작업 중 확인한다. 유효 후보가 있으면 review interrupt, 사용할 근거/후보 자체가 없으면 명시적 failed로 남긴다. 실패를 빈 레시피로 승인시키지 않는다. 시각 추론은 자동 검사 통과만으로 저장하지 않는다.
- [ ] 검토 대기는 실행 예산에 합산하지 않는다. 체크포인트에 남긴 사용 예산을 재시도·재개에서 이어 쓰며 600초를 다시 부여하지 않는다. 기존 후보 승인 해시·저장 직전 검사 보호는 유지한다.
- [ ] 합성 근거로 그래프·SQLite·색인 실패 후 원본 보존까지 검증한다. 테스트를 통과시킨 뒤 `feat: 다중 출처 검사와 보완 작업 저장 보호 적용`으로 커밋한다.

### Task 5: 예상 시간·취소·진행 표시와 실행 버전 확인

**Files:** Modify `storage.py`, `server.py`, `api_schemas.py`, `app.js`, `index.html`, `progress.py`; create `tests/test_progress.py`; extend `tests/test_http.py`, `tests/test_ui.cjs`.

**Interfaces:** `GET /api/jobs/{id}`에 progress를 추가한다. `POST /api/cancel`은 기존 RetryInput의 job_id를 사용하고 성공 시 JobAccepted를 반환한다. 상태 문자열은 기존 다섯 종류를 유지하고 취소 종료는 failed 및 취소 사유로 표현한다. 상태 API에 실행 코드·출처·검사 버전과 사용 모델을 추가한다.

- [ ] `test_no_history_has_no_numeric_eta`, `test_overdue_estimate_is_unknown_not_zero`, `test_cancel_survives_progress_update`, `test_resume_does_not_reset_budget`, `test_queued_time_is_not_analysis_time`를 작성하고 먼저 실패를 확인한다.
- [ ] progress에 실제 시작 시각·활성 경과 시간·현재 단계·보완 이유·예상 범위·추정 근거·예산 제한을 기록한다. 동일 모델과 유사 작업량의 완료 이력이 3개 미만이면 숫자 ETA는 null이다. 이력이 있으면 단계별 기록의 중간값과 사분위 범위를 작업량에 맞춰 합산한다. 최초에는 1분은 목표라고 표시하고 실측 추정이 아님을 알린다. 개인 원문을 통계에 넣지 않는다.
- [ ] 숫자 ETA가 만료되면 계산 중으로 돌리고 갱신한다. 60초 초과 시 보완 이유를 안내한다. 큐 대기·분석·검토 대기를 구별한다. 취소 요청은 별도 열에 원자적으로 쓰고 진행 JSON 갱신으로 덮지 않는다.
- [ ] UI에 경과 시간·단계·예상 범위/계산 중·지연 사유·취소 요청 결과를 표시한다. 기존 URL에는 재분석하지 않았다는 안내를 붙인다. 새 출처와 제한을 상세/검토 화면에서 확인하게 하고 알 수 없는 값은 확인 어려움으로 표시한다. 숨은 타이머·숫자 퍼센트를 만들지 않는다.
- [ ] API와 DOM에서 텍스트/오래된 작업 호환·취소 중복·이스케이프·1분 초과·모바일 좁은 폭에서 정보가 사라지지 않는 DOM 구조를 검사한다. JS 구문·양쪽 기존 DOM 검사를 통과시킨다. 시각 검증은 마지막 작업에서 별도로 수행한다.
- [ ] `feat: 분석 예상 시간과 지연 안내 및 취소 제공`으로 커밋한다.

### Task 6: 격리된 실제 평가·문서·최종 커밋

**Files:** Extend `tests/evaluate_step_quality.py`, `README.md`, 공개 `.env.example`; append `CONTEXT.md`; update 계획 체크박스와 설계 상태.

**Interfaces:** 평가 CLI에 `--fetch-video VIDEO_ID`를 추가하되 운영 API·DB 쓰기를 사용하지 않는다. 수집·모델·구간 판독 결과와 시간·누락·잘못된 추가·검토 사유를 `.runtime/adaptive-evidence-eval-*`에만 남긴다. 기존 source-db 경로는 읽기 전용이다.

- [ ] 평가 경로가 운영 경로와 같으면 거부하는 테스트와 private 원문을 stdout에 출력하지 않는 테스트를 작성해 실패를 확인한 뒤 CLI를 확장한다.
- [ ] 파스타 영상과 기존 비교 대상 영상에서 수집 성공·실패·누락·충돌을 기록한다. 실제 화면 또는 사람이 확인 가능한 원문 근거가 없으면 해당 정확도 항목을 미검증으로 남긴다. 이미 저장된 레시피를 고쳐 평가를 통과시키지 않는다. 운영 원본의 전후 해시를 읽기 전용으로 비교한다.
- [ ] 전체 Python/API, JS 구문, UI DOM, 일괄 삭제 DOM을 실행한다. 브라우저가 연결되면 실제 데스크톱·모바일에서 진행/검토/상세를 확인한다. 브라우저 미연결·모델/네트워크 실패는 그대로 보고하고 통과로 표시하지 않는다.
- [ ] 코드와 실행 결과를 독립 검토자에게 전달하고, 발견된 문제는 재현 테스트 후 수정한다. 사용자 승인 없이 새 의존성 설치나 서버 재시작으로 검증 장애를 숨기지 않는다.
- [ ] README에 수집 범위·샘플 제한·첫 실행 ETA·10분 상한·취소·기존 레시피 미교체·실행 버전 확인을 기록한다. CONTEXT에는 실제 결과와 남은 일만 추가한다. `git diff --check`와 staged diff를 확인한다.
- [ ] `docs: 보완 수집 검증 결과와 실행 안내 정리`로 커밋한다. 커밋 목록·검증·실측 시간과 정확도 한계·재시작 필요 여부를 보고한다. 원격 push·병합은 하지 않는다.

## 계획 자체 검토

설계의 출처·기본 탐색·선택 보완·근거 revision·검토·시간 안내·예산·취소·보존·평가는 작업 1~6에 대응한다. 미디어 라이브러리는 설치된 PyAV로 정했고 HTTP·용량·해상도·추가 음성·추정 이력 수의 초기값을 명시했다. 위 이름과 인자는 이후 작업이 같은 계약을 사용한다. Review focus 다섯 항목에 대응하는 실패 테스트를 각 작업에 넣었다.

완료되지 않은 것은 실제 구현과 속도·정확도·시각 검증이다. 이 계획을 작성했다는 이유로 완료 표시하지 않는다. 사용자 계획 확인과 실행 방식 선택 후 실행 스킬을 적용한다.
