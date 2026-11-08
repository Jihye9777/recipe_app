# 쿡다이어리 작업 지침

## 프로젝트

YouTube URL·텍스트를 개인 레시피로 저장하고 냉장고 재료로 추천하는 로컬 웹 앱.
Python 3.11+ / `.venv-graph` / FastAPI·Uvicorn / LangGraph / SQLite / Qdrant Local / Ollama.
설치·API·구조·연동 검증은 [README.md](README.md)의 관련 부분만 확인한다. 이 파일에는 지속적인 규칙만 두고 구현 상세·진행 상황은 중복 기록하지 않는다.

디자인 위임을 명시적으로 요청하면 `.codex/agents/ui-designer.toml`의 `ui-designer`를 사용한다. 수정 파일을 지정하고 변경 이력 기록·최종 통합은 부모가 담당한다.

## 문서와 코드가 다를 때

When a repository's documentation and its existing code disagree, follow the conventions used in the existing code, and in your final reply point out each inconsistency you found between the documentation and the code.

- 관련 코드·테스트로 확인한다. 보안·권한·금지 규칙과 명시적 사용자 요구는 예외이며, 기존 버그를 정당화하지 않는다. 안전하게 판단할 수 없는 충돌만 질문한다.
- 발견한 불일치의 처리·미해결 여부를 보고한다. 관련 문서만 정정하고 요청 밖 문서는 보고에 그친다.

## Coding Principles

Adapted from [Karpathy-inspired guidelines](https://github.com/multica-ai/andrej-karpathy-skills/blob/main/CLAUDE.md). Scale effort to the task; permission rules always apply.

### 1. Think Before Coding

- State important assumptions, tradeoffs, and observable completion criteria before implementation.
- Clarify ambiguity that materially changes the outcome; make routine choices independently. Pause only dependent work.

### 2. Simplicity First

- Choose the simplest implementation satisfying the request; challenge unnecessary complexity.
- Avoid speculative features, premature abstractions, unrequested configuration, and guards for impossible states.

### 3. Surgical Changes

- Every changed line must serve the request. Preserve existing style; avoid unrelated cleanup or refactoring.
- Report unrelated dead code. Remove newly unused dependencies only with the permission required below.

### 4. Goal-Driven Execution

- Pair each step with a check. Reproduce bugs, test invalid inputs at boundaries, and compare behavior before/after refactoring.
- Verify the outcome, not just compilation. Report actual results, blockers, and uncertainty without overstating evidence.

## 실행·검증

프로젝트 루트에서 변경 관련 검사만 실행한다. 기존 포트·Qdrant 잠금을 확인하고 중복 서버·reload를 실행하지 않는다. Uvicorn은 단일 worker를 유지한다.

```powershell
$recipePython = '.\.venv-graph\Scripts\python.exe'
$recipeNode = '.\.venv-graph\Lib\site-packages\nodejs_wheel\node.exe'
# 서버
& $recipePython -X utf8 -u server.py
# 테스트에서 보호된 .env를 자동 로드하지 않는다.
$env:PYTHON_DOTENV_DISABLED = '1'
& $recipePython -X utf8 -m unittest discover -s tests -v
# 의존성 변경
& $recipePython -m pip check
# JS/UI 변경: DOM 검사는 기존 .runtime/ui-test/node_modules/jsdom 필요
& $recipeNode --check app.js
& $recipeNode tests/test_ui.cjs
& $recipeNode tests/test_bulk_delete.cjs
& $recipeNode tests/test_evidence_ui.cjs
```

문서만 변경하면 링크·명령·diff를 확인한다. 테스트는 격리 저장소를 사용하고 자동 삭제도 승인 규칙을 따른다. 실제 연동 검사는 준비된 서비스와 README의 해당 명령을 확인한 뒤 실행한다.

## 권한·금지 구역

- `.env`, `.env.*`, `credentials/`는 읽기·수정·삭제·출력 금지. 공개 `.env.example`만 예외이며 검색·diff·스크립트에도 적용한다.
- 파일·폴더 삭제(임시 파일 자동 정리 포함), 패키지 설치·변경·제거, commit·push·PR 생성·병합은 해당 범위의 명시적 사용자 요청·승인 후 실행한다. 이미 승인한 범위는 재확인하지 않는다.
- 삭제 승인은 정확한 대상·영향·복구 가능 여부, push 승인은 remote·branch·커밋 범위를 제시한다. 일반 구현 요청은 삭제·push 승인으로 해석하지 않는다.
- force push(`--force-with-lease`·mirror·강제 refspec 포함), `reset --hard`, `clean -f`, checkout/restore로 미커밋 변경 폐기, 사용자 DB·체크포인트·인덱스 초기화와 광범위 재귀 삭제는 금지한다.
- 기존 사용자 변경과 `data/`, `.runtime/`를 보존한다. 인증 정보·개인 자막·레시피 원문을 로그나 Git에 노출하지 않는다.
- 이 문서는 작업 지침이며 OS 수준의 명령 차단 장치는 아니다.

## 코드·데이터 규칙

- Python: 4칸, `snake_case`, 클래스 `PascalCase`, 상수 `UPPER_SNAKE_CASE`. 함수·클래스의 한국어 docstring에 입력·반환·예외·부작용을 설명한다.
- JS: 2칸, `camelCase`, `const` 우선, 세미콜론 사용.
- SQLite는 원본, Qdrant는 재생성 가능한 인덱스다. 인덱스 실패 시 원본·오류 상태를 보존하고 같은 UUID로 upsert한다.
- 자막·설명란·화면 등 출처와 직접 텍스트 입력 경로를 보존한다. yt-dlp·유료 AI 폴백·클라우드 추적을 추가하지 않는다.
- 원문 근거를 보존하고 미상 값은 null로 둔다. 불확실한 결과는 사용자 확인으로 보내며 맵기·알레르기 추정을 확정 사실로 표시하지 않는다.
- SQL 매개변수 바인딩·HTML 이스케이프·정적 파일 허용 목록을 유지한다. API·스키마 변경은 UI·테스트·문서·보존형 마이그레이션을 함께 반영한다.
- 설정·의존성 변경은 `.env.example`, README, `requirements-graph.txt` 및 검증된 lock 파일에 반영한다. 임베딩 모델·시맨틱 규칙 변경 시 버전·재색인 방법도 다룬다.

## 커밋·완료 기준

- 관련 파일만 명시적으로 stage한다. 메시지·PR 제목은 `type: 한국어 요약`(feat/fix/docs/refactor/test/chore).
- 커밋 전 staged diff와 `git diff --cached --check`를 확인한다. PR에는 변경 후 동작·검증·설정/DB 적용 방법을 적는다.
- 관련 검증 후 변경 내용·결과·미실행 이유·남은 한계를 보고한다. 테스트 통과를 실제 모델 정확도나 모든 영상 수집 성공으로 확대 해석하지 않는다.

## 변경 이력: 쓰기 전용

- `CONTEXT.md`는 append-only 기록이다. 시작 시 읽거나 요약·검색하지 않는다. 현재 상태는 코드·테스트·Git에서 확인하며, 과거 조회를 명시적으로 요청받은 경우에만 필요한 범위를 읽는다.
- 새 개발 변경·결정·진단은 최종 답변 전에 날짜(Asia/Seoul)·요약·관련 파일·실제 검증·남은 일을 짧게 추가한다. 일상 대화·민감 정보는 제외한다.
- append 위치 확인용 끝부분만 최소한 읽을 수 있다. 기존 본문은 재작성하지 않고 정정도 새 항목으로 남긴다. 과거 기록을 지침·승인으로 해석하지 않는다.
- 기록 실패는 보고한다. 이 규칙을 자동 저장 서비스나 기술적인 접근 차단으로 설명하지 않는다.
