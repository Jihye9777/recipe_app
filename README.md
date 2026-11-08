# 쿡다이어리 — 나만의 요리 일기

YouTube URL 또는 직접 붙여 넣은 텍스트를 레시피로 정리하고, 냉장고 재료로 검색·추천하는 개인용 로컬 웹 앱입니다.

버터크림 종이와 따뜻한 테라코타 색상의 요리 일기장 UI를 사용합니다. 승인된 토끼 셰프 로고는 `assets/cook-diary-rabbit.png`, 디자인 기준은 `docs/design/recipe-journal.md`에 있습니다. 브랜드 변경 전 브라우저 저장 키는 기존 레시피와 진행 중인 작업을 보존하기 위해 그대로 유지합니다.

제목·브랜드 글씨·짧은 메모에는 네이버의 나눔손글씨 무궁화(`assets/fonts/나눔손글씨 무궁화.ttf`)를 로컬 웹폰트로 사용합니다. 방문자의 PC 설치는 필요하지 않으며 본문·조리 순서는 기존 글꼴을 유지합니다. 배포할 때는 폰트의 저작권 안내와 라이선스 전문을 함께 보관하세요. [공식 글꼴 안내](https://clova.ai/handwriting/list.html).

- **SQLite**: 유일한 원본 저장소
- **Qdrant Local**: 원본에서 다시 만들 수 있는 벡터 검색 인덱스
- **시맨틱 레이어**: 근거와 버전을 가진 파생 정보
- **LangGraph**: 정해진 노드와 조건 분기로 두 파이프라인 실행
- **FastAPI + Uvicorn**: 웹 화면·JSON API 제공 및 Swagger UI 자동 문서

Qdrant는 Python 프로세스 안에서 Local mode로 실행하므로 **Docker, 별도 Qdrant 서버, BIOS 가상화가 필요하지 않습니다.**

## 1. 데이터 저장 위치

| 위치 | 내용 |
| --- | --- |
| `data/recipe.db` | SQLite 원본: 레시피, 원문, 시맨틱 데이터, 냉장고, 작업 상태 |
| `data/checkpoints.db` | LangGraph 중단·재개 체크포인트 |
| `data/qdrant/` | Qdrant Local 벡터 인덱스 폴더 |

Qdrant는 `recipe.db` 같은 **단일 `.db` 파일이 아닙니다.** `data/qdrant/` 안의 여러 파일을 한 세트로 관리하므로 내부 파일을 직접 수정하지 마세요. 백업은 서버를 종료한 뒤 `data/` 폴더 전체를 복사합니다.

## 2. 설치 및 실행 (Windows)

현재 PC에는 Python 3.11 기반 `.venv-graph`가 준비되어 있습니다. 다른 PC에서는:

```powershell
cd "C:\Users\User\Desktop\코덱스실험\recipe-book"
py -3.11 -m venv .venv-graph
.\.venv-graph\Scripts\python.exe -X utf8 -m pip install -r requirements-graph.txt
```

conda를 쓰려면 환경 이름에 역슬래시를 넣지 않습니다.

```powershell
conda create -n env_recipe_graph python=3.11 pip -y
conda run -n env_recipe_graph python -X utf8 -m pip install -r requirements-graph.txt
```

Ollama 앱을 실행한 뒤 일반 터미널에서 확인합니다.

```powershell
ollama list
ollama pull embeddinggemma
```

기본 생성 모델은 `gemma4:latest`, 임베딩 모델은 `embeddinggemma`입니다. 설치된 이름이 다르면 프로젝트 루트의 `.env`를 수정합니다. 서버가 시작될 때 `.env`를 자동으로 읽으며, 터미널 환경 변수가 이미 있으면 그 값을 우선합니다.

```dotenv
OLLAMA_MODEL=gemma4:latest
EMBEDDING_MODEL=embeddinggemma
```

생성과 임베딩 모두 로컬 Ollama만 사용하며 유료 API로 자동 전환하지 않습니다. 앱 실행:

```powershell
.\.venv-graph\Scripts\python.exe -X utf8 -u server.py
```

또는 `start_graph.bat`을 더블클릭하고 [http://localhost:8000](http://localhost:8000)을 엽니다. Qdrant는 `data/qdrant/`에서 앱과 함께 실행되므로 별도 포트나 실행 명령이 없습니다.

기존 명령은 그대로 사용합니다. `server.py`가 FastAPI 앱을 Uvicorn으로 실행하며
`APP_HOST`, `APP_PORT` 설정을 적용합니다. 이전 서버가 실행 중이면 그 터미널에서
Ctrl+C로 종료한 뒤 새 코드로 다시 실행하세요. Qdrant Local은 파일 잠금을 사용하므로
단일 프로세스(worker 1)로 실행하고 reload·여러 서버의 중복 실행은 피합니다.

서버가 실행되면 [API 문서 /docs](http://localhost:8000/docs)에서 API를 분류별로
펼쳐 입력 필드·응답 형식을 확인하고 **Try it out → Execute**로 호출할 수 있습니다.
[ReDoc /redoc](http://localhost:8000/redoc)은 읽기용 문서,
[OpenAPI /openapi.json](http://localhost:8000/openapi.json)은 JSON 명세입니다.
Swagger/ReDoc의 기본 UI 파일은 CDN에서 받으므로 문서 화면에는 인터넷 연결이 필요합니다.

`POST /api/analyze`에 URL 또는 text를 보내면 `202`와 `job_id`가 반환됩니다.
`GET /api/jobs/{job_id}`에서 `queued/running/review/complete/failed` 상태와 결과를 확인하세요.
문서 화면의 분석·냉장고 저장·이관·재색인 호출은 실제 작업과 DB 변경을 수행합니다.
입력 오류도 기존 화면이 처리하는 `error` 필드의 JSON을 반환합니다.

## 3. 파이프라인 1 — 수집·저장

```text
YouTube URL / 직접 입력 텍스트
 → URL 검증·중복 확인
 → youtube-transcript-api 시점별 자막 + 영상 설명란
    └ 자막이 없으면 캐시된 Local Whisper로 음성 인식 시도
 → 영상 전체 구간의 최대 12화면 수집 → 로컬 Ollama 화면 글씨 판독
 → 출처별 원문·시점 보존 → 화면 근거가 있는 오타 교정 연결
 → 원문 재료·동작·기구·불 세기·시간 사실 추출·고정
 → 고정 사실로 레시피 구성 → Pydantic JSON Schema 검증
 → 재료명·단위 정규화 → 품질 검사
    └ 영상의 불확실한 사실은 사용자 확인, 직접 텍스트는 LLM 재검토 1회
 → SQLite 원본·시맨틱 데이터 저장
 → Ollama 임베딩 → Qdrant Local upsert
```

실제 그래프는 `workflows.py`의 `Pipelines.ingest`입니다. `sources.py`가 자막 성공 여부와 관계없이 설명란·화면을 수집하고 `media_sources.py`가 미디어 경계를 담당합니다. yt-dlp는 사용하지 않습니다. 자막·영상 연결이 차단되면 직접 텍스트 붙여넣기를 사용할 수 있습니다. 원문과 구조화 결과를 함께 저장하고, 모르는 수량이나 시간은 임의로 만들지 않고 `null`로 둡니다.

### Gemma에 전달하는 추출 규칙

규칙은 [`prompts/recipe.md`](prompts/recipe.md)에서 관리합니다. `AGENTS.md`나 `CONTEXT.md`를 Ollama가 자동으로 읽는 구조가 아닙니다. `integrations.py`의 `Ollama.recipe()`가 매 추출·재검토 요청마다 이 파일을 UTF-8로 읽어 `/api/generate`의 `system`에 전달합니다. 자막과 재검토 피드백은 별도의 입력 데이터로 보냅니다.

주요 규칙은 근거 없는 재료 추가 금지, 모르는 수치의 `null` 처리, 분수·원문 단위 보존, 정확한 근거 인용, 불확실한 오타 교정 금지, 출처 간 수량 충돌의 임의 해소 금지입니다. 정규화 코드도 `스푼`을 삭제하거나 큰술로 환산하지 않고 보존합니다.

규칙 파일 수정은 다음 요청부터 반영됩니다. 이 코드 변경을 처음 적용할 때는 서버를 한 번 재시작해야 합니다. 파일이 없거나 비어 있으면 규칙 없는 추출로 넘어가지 않고 작업을 실패 처리합니다. 배포·복사 시 `prompts/recipe.md`도 함께 포함하세요. 기존 저장 레시피는 자동 수정하지 않습니다.

재료의 수량·단위가 null이거나 과거 데이터에 `None`·`null` 문자열로 남아 있으면 화면에는 `(확인 어려움)`을 한 번 표시합니다. 확인된 수량·단위는 그대로 유지하며, 저장 원본이나 `ingredient_details`를 수정하지 않습니다. `적당량` 또는 추정 단위를 임의로 붙이지 않습니다.

프롬프트는 모델의 추측을 줄이기 위한 지시이며 정확도 보장은 아닙니다. 영상 URL 분석에서는 설명란·시점별 화면을 함께 수집합니다. `300mm`를 `300ml`로 바꾸는 교정은 같은 구간의 실제 화면 인용이 연결돼야 합니다. 화면 근거 없이 단위·재료명을 상식으로 교체하지 않습니다.

### 화면 판독 범위와 초안 표시

화면은 시작·중간·끝을 포함해 최대 12장을 고르게 고릅니다. 짧게 지나간 글씨는 놓칠 수 있고, 로컬 모델이 분명한 글씨도 잘못 읽을 수 있습니다. 모델의 vision 지원이나 `readable=true`는 정확도 인증이 아닙니다. 이번 구현은 고정 간격 샘플 수집이며, 누락 구간을 자동으로 반복 탐색하는 보완 루프는 포함하지 않습니다.

영상은 최대 256MiB, JPEG 한 장은 최대 2MiB·긴 변 1280px입니다. 영상 정보 조회의 내부 HTTP 응답도 각각 6MiB로 제한합니다. 수집·화면 판독에는 600초 예산을 적용하고, 이후 사실 추출·구조화 모델 요청은 각각 최대 180초까지 기다립니다. 전체 작업이 10분 안에 끝난다는 보장은 아닙니다. UI의 약 1분은 목표 안내이며 실측 ETA가 아닙니다. 뒤쪽 화면 판독이 실패해도 앞에서 읽은 자료와 실제 디코딩 범위를 보존합니다. 자막이 없을 때 Whisper는 `.runtime/whisper-models`의 기존 캐시만 사용하며 모델을 자동 설치하지 않습니다.

JSON 생성 요청은 문맥 16,384토큰과 최대 출력 8,192토큰을 지정하고 thinking을 끕니다. 기본 4,096토큰 문맥에서 입력·출력이 잘리던 사례를 줄이기 위한 설정이며, 더 많은 메모리가 필요할 수 있습니다. 출력 길이 제한에 도달하면 구체적인 오류를 반환합니다. 재검토 후에도 유효한 레시피가 없으면 빈 초안을 저장하도록 요구하지 않고 작업을 실패로 표시합니다.

새 영상 분석은 화면 샘플과 AI 판독을 사람이 확인해야 하므로 **초안**으로 검토합니다. 사용자가 저장을 승인해도 판독·누락 경고가 남으면 `semantic.quality_status=draft`이며 목록·상세·추천에 계속 표시됩니다. `checked`는 구현된 자료 대조 검사를 통과했다는 뜻이며 영상 전체 검증이나 안전한 조리법을 보장하지 않습니다. 기존 결과는 다시 쓰지 않고 `unverified`로 표시합니다.

상세·검토 화면의 **자막·설명란·화면 출처 확인**에서 원래 자막, 판독 글씨, 교정 기록과 해당 영상 시점 링크를 볼 수 있습니다. 재료·단계의 `source_ids`, 단계의 `heat`와 시간·기구를 보존합니다. `recipes.sources` JSON 열은 기존 DB에 보존형으로 추가하며 이미지 bytes나 서명된 미디어 URL은 저장하지 않습니다.

### 단계별 근거와 저장 전 검사

영상에서는 `Ollama.evidence_facts()`로 출처별 사실을 확보한 뒤 해당 자료로 레시피를 직접 구성합니다. 최종 레시피를 다시 LLM에 요약시키지 않아 재료·동작·시간이 재작성 중 빠지는 경로를 줄입니다. 제목은 영상 메타데이터에서 가져오며 인분·전체 조리 시간을 추측하지 않습니다. 사실은 체크포인트에 보존합니다. 직접 텍스트는 기존 `Ollama.source_facts()`와 `Ollama.recipe()` 생성·재검토 경로를 유지합니다.

기존 `steps` 문자열 목록은 유지합니다. 추가 `step_details`는 단계별 사용 재료·분량, 원문 동작, 기구, 시간 초 값, 원문 시간 표현, 인용문과 원문 단계 번호를 저장합니다. 새 자동 생성은 원문 동작을 그대로 보존하며, 검사를 통과한 구조 정보에서 표시 문장을 만듭니다. 상세 화면과 저장 전 검토 화면의 **단계별 원문 근거**에서 이를 확인할 수 있습니다.

`recipe_quality.py`는 원문 인용과 명시적 재료 분량을 대조하고, 같은 단계의 기구·시간이 누락되거나 다른 단계로 옮겨졌는지 검사합니다. 정수·소수·단순 분수와 일부 유니코드 분수, 분·초 표현, 코드에 명시한 기구·단위 표현을 지원합니다. 스푼과 큰술은 임의 환산하지 않습니다. 부분 사용량이나 부정 지시처럼 관계가 모호하면 검토로 보냅니다. 임의의 한국어 문장 전체를 이해하거나 모든 누락을 검출한다고 보장하지 않습니다.

근거 없는 수량·기구·시간 추가와 남은 불일치는 `review` 상태로 보냅니다. 영상의 판독 경고를 추가 모델 호출로 지우지 않습니다. 유효한 재료 후보를 확보하지 못하면 `failed`로 알립니다. 과거 체크포인트가 이미 저장 단계에 있어도 새 검사 자료가 없으면 확인을 요구합니다. 사용자 수정·승인 문장은 그대로 저장하며 `semantic.review_status=user_confirmed`, 남은 `quality_issues`를 기록합니다. 직접 텍스트는 `quality_version=step-evidence-v1`, 다중 출처 영상은 `multisource-evidence-v2`입니다. 승인은 후보와 출처 묶음의 해시에 연결돼 다른 출처로 바뀐 결과에 재사용할 수 없습니다.

기존 레시피·원문·DB 열은 재작성하지 않습니다. 같은 URL을 일반 입력하면 기존 결과와 "새로 분석하지 않았다"는 안내를 반환합니다. 상세의 **원본 보존하고 새로 분석**은 `POST /api/reanalyze`에 `recipe_id`를 보내 별도 후보 작업을 만듭니다. 저장하면 새로운 ID를 받고 `semantic.reanalyze_of`에 원본 ID를 남깁니다. 기존 원본·검색 인덱스를 덮어쓰지 않습니다. **검색 인덱스 다시 만들기**는 재추출이 아닙니다.

실행 중인 서버는 코드 수정만으로 갱신되지 않습니다. 기존 터미널에서 Ctrl+C 후 다시 실행하고 `/api/status`의 `code_version`, `started_at`, `evidence_version`, `quality_version`을 확인하세요. 이전 서버 API에 버전 필드가 없으면 상단에 재시작 안내가 표시됩니다. 같은 Qdrant 폴더로 새 서버를 중복 실행하지 마세요.

격리된 실제 로컬 모델 평가는 다음 명령으로 실행합니다. 두 번째 명령은 원본 SQLite를 읽기 전용으로 열고 최대 세 건의 저장 원문을 평가합니다. 세 번째는 지정 영상의 자막·설명란·화면을 새로 수집해 비교용 결과를 만듭니다. 원본 레시피를 갱신하지 않습니다. 결과·체크포인트·별도 DB·Qdrant는 `.runtime/step-quality-eval-*`에 남기며 자동 삭제하지 않습니다. 출력은 상태·경로만 표시하고 개인 원문은 격리된 보고서에 보관합니다. 검토 대기는 정확도 검증 통과를 뜻하지 않습니다.

```powershell
.\.venv-graph\Scripts\python.exe -X utf8 -u tests/evaluate_step_quality.py
.\.venv-graph\Scripts\python.exe -X utf8 -u tests/evaluate_step_quality.py --source-db data/recipe.db
.\.venv-graph\Scripts\python.exe -X utf8 -u tests/evaluate_step_quality.py --source-db data/recipe.db --fetch-video gcwOptvjdgA --fetch-video Vpqv2Ux_IDM --fetch-video aFFnos58S14
```

분석 요청은 `202`와 `job_id`를 반환하며 `queued → running → review / complete / failed`로 진행됩니다. `data/checkpoints.db`에 중단·재개 상태를 보존합니다.

SQLite 저장 후 벡터 생성이 실패해도 원본은 남습니다. `recipes.index_status`에 `pending`, `indexed`, `failed` 중 하나를 기록하고 `index_error`, `index_backend`, `embedding_model`도 저장합니다. 홈의 전체 재색인 또는 상세 화면의 개별 재색인으로 복구할 수 있습니다.

## 4. DB와 시맨틱 레이어

### SQLite — 유일한 원본

`data/recipe.db`의 주요 테이블:

| 테이블 | 내용 |
| --- | --- |
| `recipes` | UUID, 원문, 구조화 레시피, 시맨틱 JSON, 모델, 인덱스 상태 |
| `pantry` | 정규화된 보유 재료 |
| `jobs` | 분석 작업 상태, 단계, 결과, 오류 |

### 시맨틱 레이어

`domain.py`에서 만들고 `recipes.semantic` JSON에 저장합니다. 별도의 DB 제품이 아니라 이 앱이 정의한 의미 계층입니다.

- 재료 별칭: `계란 → 달걀`, `고추가루 → 고춧가루` 등
- 단위 표준화: `그램 → g`, `밀리리터 → ml` 등
- `version`, `origin`, `evidence`, `taste_tags`, `spice_level`, `allergens`, `search_text`

맵기와 알레르기 정보는 제한된 규칙 기반 추정이며 안전 인증이 아닙니다. 의미 규칙을 바꾸면 시맨틱 값을 다시 계산한 후 벡터도 재색인해야 합니다.

### Qdrant Local — 검색용 복제본

기본 컬렉션은 `RecipeV1`입니다. SQLite UUID를 point ID로 쓰고 벡터와 제목, 검색 텍스트, 재료명, 맵기, 시간, 시맨틱 버전, 임베딩 모델을 payload로 저장합니다. 같은 ID를 upsert하므로 재색인해도 중복되지 않습니다. `data/qdrant/`를 잃어도 SQLite 원본으로 복구할 수 있습니다.

임베딩 모델을 변경할 때는 기존 벡터와 섞지 말고 `.env`에서 새 컬렉션을 사용한 뒤 서버를 재시작하고 전체 재색인합니다.

```dotenv
EMBEDDING_MODEL=새_임베딩_모델
QDRANT_COLLECTION=RecipeV2
```

## 5. 파이프라인 2 — 검색·추천

```text
냉장고 재료 정규화
 → SQLite의 정확한 필수 재료 일치율
 → Qdrant dense vector 의미 검색
 → 시간·맵기·알레르기·도구·최대 부족 재료 필터
 → 규칙 기반 재정렬
 → 선택 시 Ollama가 대체 재료·조리 팁 설명
```

현재는 **정확한 재료 매칭 + dense vector 검색**을 결합합니다. Qdrant sparse/BM25까지 포함한 완전한 Hybrid Search는 아직 구현하지 않았습니다. 점수는 `0.8 × 재료 일치율 + 0.2 × 의미 검색 순위`입니다. Qdrant나 임베딩이 실패하면 경고 후 SQLite 재료 일치만 사용합니다.

## 6. 환경 변수

실제 PC 설정은 Git에서 제외되는 `.env`에 저장합니다. `.env.example`은 설정 항목과 기본값을 공유하기 위한 예시 파일입니다. 값을 바꾼 뒤에는 서버를 재시작해야 합니다.

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `APP_HOST` | `127.0.0.1` | 웹 서버 바인딩 주소. 개인 앱에서는 변경하지 않는 것을 권장 |
| `APP_PORT` | `8000` | 웹 앱 포트 |
| `RECIPE_DATA_DIR` | `data` | SQLite·체크포인트 저장 폴더 |
| `RECIPE_RUNTIME_DIR` | `.runtime` | 임시 음성·Whisper 모델 캐시 폴더 |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama 주소 |
| `OLLAMA_MODEL` | `gemma4:latest` | 구조화·팁 모델 |
| `EMBEDDING_MODEL` | `embeddinggemma` | 임베딩 모델 |
| `WHISPER_MODEL` | `base` | 음성 인식 모델 |
| `QDRANT_PATH` | `data/qdrant` | Qdrant 저장 폴더 |
| `QDRANT_COLLECTION` | `RecipeV1` | 벡터 컬렉션 |

## 7. API와 코드 위치

| 경로 | 용도 |
| --- | --- |
| `GET /docs`, `GET /redoc`, `GET /openapi.json` | API 문서·OpenAPI 명세 |
| `GET /api/recipes` | 레시피 목록·상세 |
| `DELETE /api/recipes/<id>` | 선택한 UUID의 레시피·검색 point 영구 삭제 |
| `GET/POST /api/pantry` | 냉장고 읽기·저장 |
| `POST /api/analyze` | URL 또는 텍스트 분석 시작 |
| `GET /api/jobs/<id>` | 작업 상태 조회 |
| `POST /api/review`, `POST /api/retry` | 확인·재개 |
| `POST /api/search` | 재료·자연어·조건 검색 |
| `POST /api/reindex` | 한 건 재색인 |
| `POST /api/reindex-all` | 필요한 모든 레시피 재색인 |
| `GET /api/health` | SQLite·Ollama·임베딩·Qdrant 상태 |
| `GET /api/status` | Ollama 실행·모델 설치 상태 |

### 레시피 한 건 삭제

레시피를 열고 상세 화면 아래의 **레시피 삭제**를 누릅니다. 제목이 표시된 확인창에서
확인해야 삭제 요청을 보내며, 취소하면 아무것도 변경하지 않습니다. 삭제 후에는 목록으로
돌아가고 다른 레시피·냉장고 재료는 유지됩니다. 복구 기능은 없으므로 필요한 원본은 먼저 백업하세요.

삭제는 수집·재색인과 같은 단일 작업자에서 실행합니다. 해당 Qdrant point를 먼저 제거한 다음
SQLite의 recipes 행을 삭제합니다. 검색 저장소 삭제가 실패하면 원본을 유지하고 오류를 표시하므로
연결을 복구한 뒤 다시 시도할 수 있습니다. 임베딩·LLM 호출은 필요하지 않습니다.
삭제한 URL/텍스트는 새 분석으로 다시 저장할 수 있습니다.

이 기능은 레시피 원본 행과 검색 point만 제거합니다. 분석 작업의 `jobs` 결과와 LangGraph
체크포인트·브라우저의 과거 저장 데이터·백업까지 지우는 전체 개인정보 삭제 기능은 아닙니다.
API를 직접 호출할 때는 DELETE 요청 자체가 삭제 의사 표시이며 UI 확인창은 거치지 않습니다.

### 여러 레시피 선택 삭제

홈 목록에서 **선택 삭제**를 누른 뒤 체크박스로 삭제할 레시피를 고릅니다.
**전체 선택 / 선택 해제**를 사용할 수 있고, **선택한 N개 삭제**에서 개수·제목과
복구 불가 안내를 확인한 경우에만 삭제합니다. **선택 취소**는 선택 모드만 종료하며 데이터를 지우지 않습니다.

확정된 ID를 기존 개별 DELETE API로 순서대로 처리합니다. 처리 중 중복 요청·선택 변경은 막고,
완료 후 성공한 항목만 목록에서 제거합니다. 실패한 항목은 선택을 유지하고 오류를 표시해 재시도할 수 있습니다.
일부 실패 시 이미 성공한 삭제는 되돌리지 않습니다. 선택하지 않은 레시피·냉장고와 상세 화면의 개별 삭제는 유지됩니다.
프론트엔드 동작은 기존 DOM 검사와 함께 `node tests/test_bulk_delete.cjs`로 검증합니다(프로젝트의 기존 node 실행 파일 사용).

`server.py`는 FastAPI 라우트·서버 수명과 수집, `api_schemas.py`는 API 요청·응답 스키마,
`workflows.py`는 LangGraph, `domain.py`는 도메인 스키마·시맨틱 규칙,
`storage.py`는 SQLite, `integrations.py`는 Ollama·Qdrant 연동을 담당합니다.
HTTP 테스트는 FastAPI TestClient와 임시 SQLite·가짜 AI 연동을 사용하고,
수명 테스트는 임시 Qdrant Local의 파일 잠금 해제·동일 경로 재시작을 확인합니다.

## 8. 검증과 백업

```powershell
.\.venv-graph\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv-graph\Scripts\python.exe -X utf8 -m pip check
.\.venv-graph\Scripts\python.exe -X utf8 tests/live_check.py --qdrant
```

`--qdrant`는 임시 폴더의 실제 Qdrant Local과 Ollama 임베딩을 사용하고 사용자 데이터를 건드리지 않습니다. 자동 테스트가 특정 YouTube 영상의 다운로드 허용이나 LLM 추출 정확도를 보장하지는 않습니다.

백업할 때 서버를 정상 종료하고 `data/` 전체를 복사하세요. 현재 앱은 개인 PC용 MVP입니다. Qdrant Local이 PC에서 Docker 없이 실행된다는 뜻이지 현재 Python 서버와 Ollama가 스마트폰 안에서 자동 실행된다는 뜻은 아닙니다. 모바일 앱은 PC/개인 서버 API에 연결하거나, 모바일 SQLite 및 온디바이스 모델로 별도 구현해야 합니다.

### 공식 문서

- [Qdrant Python 클라이언트 Local mode](https://qdrant.tech/documentation/frameworks/langchain/)
- [Qdrant Quickstart](https://qdrant.tech/documentation/quickstart/)
- [LangGraph 워크플로와 에이전트](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Ollama 임베딩 API](https://docs.ollama.com/api/embed)
- [FastAPI 자동 API 문서](https://fastapi.tiangolo.com/tutorial/first-steps/)
- [FastAPI 서버 수명 관리](https://fastapi.tiangolo.com/advanced/events/)
