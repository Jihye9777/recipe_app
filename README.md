# 한입노트 — 로컬 레시피 북

YouTube URL 또는 직접 붙여 넣은 텍스트를 레시피로 정리하고, 냉장고 재료로 검색·추천하는 **단일 사용자 로컬 웹 앱**입니다.

**SQLite가 원본, Weaviate는 재생성 가능한 검색 인덱스, 시맨틱 레이어는 근거와 버전을 가진 파생 정보**입니다. 두 파이프라인은 LangGraph의 정해진 노드·조건 분기로 실행합니다. LLM이 임의의 도구를 선택하는 자율 에이전트가 아닙니다.

## 1. 시작하기 (Windows)

### 현재 작업 환경

- 기존 `env_recipe`는 Python 3.9이므로 새 LangGraph 의존성을 위해 Python 3.11 환경이 필요합니다. 기존 conda 환경은 변경하지 않았습니다.
- `env_recipe_graph` 생성은 Anaconda 저장소 연결 실패로 완료되지 않았습니다.
- 대신 설치된 Python 3.11로 프로젝트 안에 `.venv-graph`를 만들고 `requirements-graph.txt` 패키지 설치를 완료했습니다.
- `start_graph.bat` / `start_app.bat`을 더블클릭하면 `.venv-graph`를 우선 사용합니다. 없으면 conda의 `env_recipe_graph`를 사용합니다.
- Docker Desktop 4.90.0과 Ollama 임베딩 모델 `embeddinggemma` 설치를 완료했습니다.
- **현재 PC의 BIOS 가상화가 비활성화되어 Weaviate 실행 검증은 막혀 있습니다.** Docker 로그에 `HCS_E_HYPERV_NOT_INSTALLED`, CPU 상태에 `VirtualizationFirmwareEnabled=False`가 확인됐습니다. 아래 ‘현재 PC에서 남은 설정’을 먼저 확인하세요.

### A. Python 패키지 설치 (다른 PC / conda를 사용할 때)

Anaconda Prompt에서 프로젝트 폴더로 이동해 실행합니다. `env_recipe_graph`에 역슬래시를 넣지 마세요.

```powershell
cd "C:\Users\User\Desktop\코덱스실험\recipe-book"
conda create -n env_recipe_graph python=3.11 pip -y
conda run -n env_recipe_graph python -X utf8 -m pip install -r requirements-graph.txt
```

`conda`가 인식되지 않으면 Anaconda Prompt를 사용하거나 실행 파일의 절대 경로를 사용합니다. 이 PC에서는 `C:\ProgramData\anaconda3\Scripts\conda.exe`입니다. PowerShell에서는 실행 경로 앞에 `&`가 필요합니다.

Python 3.11로 가상환경을 직접 만드는 대안:

```powershell
py -3.11 -m venv .venv-graph
.\.venv-graph\Scripts\python.exe -X utf8 -m pip install -r requirements-graph.txt
```

`requirements.txt`는 기존 자막·음성 패키지 목록이고, **전체 앱에는 `requirements-graph.txt`가 필요**합니다. 한글 Windows의 인코딩 문제를 줄이기 위해 `-X utf8`을 사용합니다.

이번 검증에 사용한 전체 패키지 버전은 `requirements-graph.lock.txt`에 기록했습니다. Windows/Python 3.11에서 같은 버전을 재현하려면 `python -X utf8 -m pip install -r requirements-graph.lock.txt`를 사용하세요.

### B. Ollama 준비

Ollama 앱을 실행한 다음 일반 터미널에서 확인합니다. 모델과 대화 중인 `>>>` 프롬프트에 입력하는 명령이 아닙니다.

```powershell
ollama list
ollama pull embeddinggemma
```

생성 모델 기본값은 기존 설정을 유지한 `gemma4:latest`입니다. `ollama list`에 표시되는 **설치된 모델 이름과 정확하게 일치**하도록 설정하세요. 생성 모델과 임베딩 모델은 별개입니다.

```powershell
$env:OLLAMA_MODEL = "gemma4:latest"
$env:EMBEDDING_MODEL = "embeddinggemma"
```

이 변수는 해당 터미널과 그 터미널에서 실행하는 앱에만 적용됩니다. `.env` 자동 로딩은 구현하지 않았습니다. 모델을 바꾼 터미널에서 `python server.py`를 실행하세요. Ollama가 실행되지 않았다면 `ollama serve`를 실행하되, 이미 실행 중일 때는 중복 실행하지 않습니다.

생성/임베딩 모두 로컬 Ollama API를 사용하며 OpenAI API 키·유료 클라우드 모델로 자동 전환하지 않습니다. 모델 다운로드에는 인터넷과 디스크 공간이 필요하고, 실행에는 RAM/CPU/GPU·전력이 필요합니다.

### C. Weaviate 실행

Docker Desktop을 설치·실행한 다음 프로젝트 폴더에서:

```powershell
docker compose up -d
docker compose ps
Invoke-WebRequest http://127.0.0.1:8080/v1/.well-known/ready
```

`compose.yaml`은 Weaviate 버전을 고정하고 데이터를 Docker의 `weaviate_data` named volume에 저장합니다. REST 8080과 gRPC 50051 모두 Python 클라이언트에 필요합니다. 임베딩은 앱이 직접 전달하므로 Weaviate가 Ollama에 연결하는 구성은 아닙니다.

컨테이너를 잠시 끄려면 `docker compose stop`을 사용합니다. `docker compose down -v`는 검색 데이터 볼륨을 지우므로 일반 종료에 사용하지 마세요.

#### 현재 PC에서 남은 설정

현재 AMD Ryzen 5 3600 CPU는 가상화 기능을 지원하지만 펌웨어에서 비활성화되어 있습니다. 앱 코드로 BIOS 설정을 켤 수는 없습니다. 작업을 저장한 뒤 PC 제조사 안내에 따라 BIOS/UEFI에서 가상화(AMD에서는 보통 `SVM Mode`)를 활성화해야 합니다. 메뉴 위치는 메인보드마다 다릅니다. 자동 재부팅이나 BIOS 설정 변경은 하지 않았습니다.

Windows의 ‘가상 머신 플랫폼’ 기능도 필요합니다. BIOS 설정 후에도 Docker가 시작되지 않으면 관리자 PowerShell에서 `wsl --install --no-distribution`을 실행하고 Windows 안내에 따라 재시작하세요. [Microsoft WSL 문제 해결 문서](https://learn.microsoft.com/en-us/windows/wsl/troubleshooting#installation-issues)의 가상화/Virtual Machine Platform 항목을 참고하세요.

재시작 후 Docker Desktop 실행 → 프로젝트 폴더에서 `docker compose up -d` → 아래 통합 검증 순서로 진행합니다. Docker가 켜지지 않은 상태에서 앱은 SQLite 원본 저장과 재료 이름 기반 추천은 제공하지만 Weaviate 의미 검색은 사용할 수 없습니다.

### D. 앱 실행

기존 8000번 서버가 있으면 해당 터미널에서 Ctrl+C로 종료하고 새 서버를 한 번만 실행합니다.

```powershell
.\.venv-graph\Scripts\python.exe -X utf8 -u server.py
```

또는 conda 환경을 설치한 경우:

```powershell
conda run --no-capture-output -n env_recipe_graph python -X utf8 -u server.py
```

브라우저에서 [한입노트](http://localhost:8000)를 엽니다. 서버 창은 닫지 마세요. 코드를 바꾼 뒤에는 서버 재시작과 브라우저 새로고침이 필요합니다.

| 구성 요소 | 주소 | 역할 |
| --- | --- | --- |
| 앱 | `http://127.0.0.1:8000` | 사용자가 여는 화면·앱 API |
| Ollama | `http://127.0.0.1:11434/api/tags` | 설치된 모델 확인 |
| Weaviate | `http://127.0.0.1:8080/v1/.well-known/ready` | 검색 DB 준비 상태 |
| Weaviate gRPC | `127.0.0.1:50051` | Python 클라이언트 통신, 웹 화면 아님 |

상단 AI 배지는 생성 모델 상태를, 본문 위 상태 줄은 **SQLite·생성 모델·임베딩 모델·Weaviate**를 각각 보여줍니다. 상태 줄은 `/api/health`를 30초마다 조회합니다. 모델 준비 여부는 설치 확인이고 실제 추론 품질을 보장하는 검사는 아닙니다. Weaviate 준비 확인은 REST readiness와 gRPC 포트 연결을 함께 검사합니다.

## 2. 파이프라인 1: 수집·정형화·저장

```text
URL / 붙여 넣은 텍스트
  → URL 검증·중복 확인
  → youtube-transcript-api → 실패 시 pytubefix 오디오 다운로드 + faster-whisper
  → 전처리
  → Ollama 구조화 + Pydantic(JSON Schema) 검증
  → 재료명·단위 정규화 + 품질 검사
       ├─ 통과 ───────────────────────────┐
       └─ LLM 재검토 1회 → 다시 검사        │
              ├─ 통과 ──────────────────┤
              └─ 불확실 → 사용자 확인 ────┤
                                          ↓
                     SQLite 원본 저장 + 시맨틱 속성 생성
                                          ↓
                              Ollama 임베딩 → Weaviate
```

실제 그래프는 `workflows.py`의 `Pipelines.ingest`입니다. URL은 허용된 YouTube 호스트와 11자리 영상 ID를 검증하고, 수집에는 정규화한 주소만 전달합니다. 동일 영상의 공유·추적 파라미터가 달라도 `youtube:<영상 ID>`로 한 번만 저장합니다. 직접 입력 텍스트는 앞뒤 공백 제거 후 SHA-256을 중복 키로 사용하므로 내용이 바뀌면 별도 레시피입니다.

- 자막은 한국어 우선, 영어 차선입니다. 자막 추출 실패 시 Whisper를 시도하지만 **오디오 다운로드 자체가 막히면 Whisper도 시작할 수 없습니다.** yt-dlp는 사용하지 않습니다.
- 기존 `pytube==15.0.0`는 실제 영상에서 HTTP 400으로 실패해 `pytubefix==11.1.0`로 교체했습니다. Whisper 모델은 `.runtime/whisper-models`에 캐시하며 임시 오디오는 처리 후 삭제합니다. Hugging Face의 공개 모델 다운로드에는 유료 API 키가 필요하지 않습니다.
- 직접 텍스트를 넣으면 네트워크 수집을 건너뜁니다. 가장 먼저 이 경로로 LLM·DB 파이프라인을 점검하는 것을 권장합니다.
- 전처리는 공백/줄바꿈 정리입니다. 원문은 따로 보존합니다. 60,000자 초과는 조용히 자르지 않고 오류로 안내합니다. 모델 문맥 한도는 그보다 작을 수 있으므로 긴 영상은 필요한 부분을 나누어 입력하세요. 자동 청크 요약은 미구현입니다.
- 생성된 JSON의 필수 필드·형식·수량 범위를 검사합니다. 모르는 수량·시간은 `null`입니다.
- 재료마다 `raw_name`(원문), `name`(정규 이름), `quantity`, `unit`, `optional`, `evidence`(원문 인용)를 갖습니다.
- 품질 검사는 근거 문장이 원문에 있는지, 원문 이름과 정규 이름이 사전상 대응하는지, 수량에 단위가 있는지 확인합니다. 모든 조리 단계의 사실성을 증명하는 검증기는 아닙니다.
- 실패 시 LLM 재검토는 최대 한 번입니다. 계속 불확실하면 `interrupt()`로 멈추고 화면에 원문·문제 목록·편집 가능한 JSON을 보여줍니다. 사용자가 확인하면 `Command(resume=...)`로 이어서 저장합니다. 원본 없는 확신성 자동 보정은 하지 않습니다.
- 현재 사용자 확인 UI는 JSON 편집형 MVP입니다. 일반 사용자용 재료 행 편집기는 후속 개선 대상입니다.

### 비동기 작업과 복구

분석 요청은 `202 + job_id`를 즉시 반환하고 화면이 진행 단계를 조회합니다. `data/checkpoints.db`에 LangGraph 상태가, `data/recipe.db`의 `jobs`에 화면용 작업 상태가 저장됩니다.

상태는 `queued → running → review / complete / failed`입니다. 확인 대기 상태는 서버 재시작 후에도 같은 작업 ID로 이어갈 수 있습니다. 실패 단계는 화면의 ‘중단된 단계 재시도’로 재실행합니다. 서버가 실행 중에 종료되어 `running`으로 남았다면 ‘서버 재시작 후 작업 재개’를 누릅니다. 최초 요청 원문도 `jobs.payload`에 저장하므로 첫 체크포인트 기록 전에 종료된 새 작업도 복구합니다. 이전 버전에서 원문이 기록되지 않은 작업은 새 분석이 필요합니다.

무제한 자동 재시도는 없습니다. 같은 작업의 중복 동시 실행을 막고, SQLite 고유 키 및 Weaviate의 동일 UUID upsert로 재실행 시 중복 저장을 방지합니다. SQLite와 Weaviate를 묶는 분산 트랜잭션은 없습니다.

## 3. DB 체계와 시맨틱 레이어

### SQLite: 유일한 원본 저장소

파일: `data/recipe.db`. 서버가 실행되는 **PC의 디스크**에 저장되며 브라우저 localStorage가 원본이 아닙니다.

| 테이블 | 저장 내용 |
| --- | --- |
| `recipes` | UUID, 고유 source_key, 원문 URL/자막, 정형 레시피 JSON, 시맨틱 JSON, 모델 이름, index_status/index_error, 생성 시간 |
| `pantry` | 정규화한 보유 재료 이름 |
| `jobs` | 작업 ID, 상태, 실행 단계, 결과 또는 확인 요청, 오류 |

현재 재료/단계는 별도 관계형 자식 테이블이 아니라 검증된 JSON 컬럼으로 저장합니다. 초기 개인 앱을 위한 선택이며, 사용자별 공유·대규모 통계가 필요해지면 테이블 정규화와 PostgreSQL 전환을 검토합니다. PostgreSQL 드라이버/이관 기능은 이번 구현에 포함하지 않았습니다.

### 시맨틱 레이어: 규칙·어휘 사전·근거·버전

`domain.py`에서 생성하고 SQLite의 `semantic` JSON에 보존합니다. 별도 DB 제품 이름이 아니라, 데이터에 의미를 부여하는 앱 계층입니다.

- 별칭: `계란 → 달걀`, `고추가루 → 고춧가루`, `올리브오일 → 올리브유`. 문자열 일부를 지우는 방식이 아닌 정확한 별칭 매핑입니다.
- 단위: `그램 → g`, `밀리리터 → ml` 등 표기를 통일합니다. g↔ml 밀도 환산, 큰술↔g 환산은 하지 않습니다. 모호한 `스푼`은 단위를 `null`로 두고 수량이 있으면 확인 요청을 합니다.
- `version=recipe-semantic-v1`, `origin=rule_estimate`, `evidence`, `taste_tags`, `spice_level`, `allergens`, `allergen_status`, `search_text`를 저장합니다.
- 매운맛은 청양고추가 있으면 3, 고춧가루·고추장·고추가 있으면 2, 근거가 없으면 `null`입니다. 실제 맵기·양·개인 취향을 측정한 점수가 아닙니다. `null`은 ‘안 맵다(0)’가 아닙니다.
- `review_status`는 자동 검사 통과 또는 사용자 확인을 기록합니다. 사용자 확인은 알레르기 안전 인증과 다릅니다.
- 알레르기 매핑은 제한적이고 복합 조미료·교차 오염을 포괄하지 못하므로 항상 `unverified`입니다. **알레르기 조건을 입력하면 현재 레시피는 모두 제외**하는 보수적 정책입니다. ‘제외 재료’ 기능은 이름 필터일 뿐 안전성 판정이 아닙니다.

추후 의미 사전/규칙을 바꾸면 버전을 올리고 **SQLite의 시맨틱 데이터도 재계산한 뒤** 인덱스를 재생성해야 합니다. 현재 ‘검색 인덱스 다시 만들기’는 저장된 시맨틱 값으로 임베딩/Weaviate만 갱신합니다.

### Weaviate: 검색용 복제본

컬렉션 기본값 `RecipeV1`. SQLite UUID를 그대로 객체 UUID로 사용합니다. 제목, 검색 텍스트, 재료 이름, 매운맛, 시간, 시맨틱 버전, 임베딩 모델과 벡터를 저장합니다. 원문 자막 전체를 여기서 관리하지 않습니다.

SQLite에 먼저 커밋한 다음 임베딩·인덱싱을 합니다. 실패하면 레시피는 정상 보존하고 `index_status=failed`, 원인을 `index_error`에 남깁니다. 상세 화면의 **검색 인덱스 다시 만들기**로 복구할 수 있습니다. 중간 종료로 `pending`이 남아도 같은 방법으로 복구합니다. 자동 outbox 소비자/예약 재색인은 아직 없습니다.

생성 모델을 바꾸는 것과 달리 **임베딩 모델 변경 시 기존 벡터와 섞으면 안 됩니다.** `EMBEDDING_MODEL`과 `WEAVIATE_COLLECTION`을 새 이름으로 함께 설정한 뒤 모든 레시피를 재색인하세요. 같은 차원이어도 다른 모델 벡터를 혼합하지 마세요.

## 4. 파이프라인 2: 검색·추천

`workflows.py`의 `Pipelines.search`는 `normalize_pantry → match_ingredients → retrieve → filter_rerank → explain` 순서로 실행합니다. 재료 일치율은 SQL 원본으로 먼저 계산하고 의미 검색 순위와 합칩니다.

1. 보유 재료와 레시피 필수 재료의 **정확한 정규 이름**을 비교합니다. 선택 재료는 필수 분모에서 제외합니다.
2. Weaviate가 BM25와 벡터를 섞는 hybrid query를 수행합니다 (`alpha=0.35`, 상위 50개). 예: ‘매운 국물 요리’. SQL 후보도 함께 유지해 검색 상위권 밖에 있는 정확한 재료 일치를 놓치지 않습니다.
3. 최대 시간, 최소 매운맛, 제외 재료, 알레르기, 보유 도구, 최대 부족 재료 수를 적용합니다. 시간/맵기/도구 조건이 있을 때 관련 값이 미상이면 제외합니다. 도구는 이름 정확 일치이며 빈 입력은 제한 없음입니다.
4. `0.8 × 필수 재료 일치율 + 0.2 × hybrid 순위 점수`로 정렬해 10개를 반환합니다. hybrid 순위 점수는 검색 결과 순번을 0~1로 환산한 값이며 모델의 확신도가 아닙니다.
5. 체크박스를 켜면 상위 3개에 대해 Ollama가 부족 재료·대체안·조리 팁을 설명합니다. 부족 재료 목록 자체는 LLM이 아닌 규칙으로 계산합니다. 설명은 원본 레시피를 변경하지 않습니다.

자연어 질의는 순위에 영향을 주는 **소프트 조건**입니다. ‘매운 요리만’ 확실히 제한하려면 매운맛 필터를 사용하세요. Weaviate/임베딩 연결 실패 시 경고와 함께 SQLite 재료 일치만으로 추천합니다. 그때 의미 검색이 성공한 것처럼 표시하지 않습니다.

냉장고는 현재 재료 종류만 저장합니다. 양·유통기한은 관리하지 않으므로 100% 일치해도 ‘바로 만들 수 있음’ 대신 **수량 확인 필요**라고 표시합니다.

## 5. 기존 localStorage 데이터 가져오기

예전 앱을 사용한 **같은 브라우저·같은 주소**로 접속하면 홈에 ‘이 브라우저의 예전 레시피를 SQLite로 가져오기’ 버튼이 나타납니다. `localhost`와 `127.0.0.1`은 브라우저 저장 영역이 다릅니다.

버튼으로 기존 레시피를 SQL에 복사하며 브라우저 데이터는 삭제하지 않습니다. `legacy:<기존 id>` 고유 키로 재실행 시 중복 저장을 막습니다. 가져온 레시피는 원문 근거가 없는 과거 데이터이고 검색 인덱스는 `pending`입니다. 상세 화면에서 재색인할 수 있습니다.

기존 ‘소금 1큰술’ 같은 문자열은 임의로 양을 분해하지 않고 원래 이름으로 보존하므로 신규 구조화 데이터보다 재료 매칭 품질이 낮을 수 있습니다. 정확한 정규화를 원하면 해당 원문을 새로 분석하세요. 기존 냉장고 localStorage는 자동 이관하지 않으며 화면에서 다시 추가해야 합니다. 브라우저에는 마지막 작업 ID만 추가로 저장합니다.

## 6. API 및 코드 위치

| 메서드/경로 | 용도 |
| --- | --- |
| `GET /api/recipes` | SQLite 레시피 목록/상세 데이터 |
| `GET /api/pantry`, `POST /api/pantry` | 보유 재료 읽기/교체, body: `{"pantry":["달걀"]}` |
| `POST /api/analyze` | `{"url":"https://youtu.be/..."}` 또는 `{"text":"레시피 원문"}`, 202와 job_id 반환 |
| `GET /api/jobs/<job_id>` | 상태·단계·결과·확인 요청 |
| `POST /api/review` | `{"job_id":"...","approved":true,"recipe":{...}}` |
| `POST /api/retry` | `{"job_id":"..."}`, 실패/중단 작업의 체크포인트 재개 |
| `POST /api/search` | pantry, query, max_time, min_spice, max_missing, exclude_ingredients, allergens, tools, tips |
| `POST /api/reindex` | `{"id":"레시피 UUID"}`, 기존 SQL 원본으로 검색 인덱스 복구 |
| `POST /api/import` | 기존 UI 형식의 `{"recipes":[...]}` 이관 |
| `GET /api/status` | Ollama 생성 모델 상태 |
| `GET /api/health` | SQLite·생성 모델·임베딩 모델·Weaviate 개별 준비 상태 |

모든 POST는 `Content-Type: application/json`이 필요합니다. 검색·재색인은 동기 요청이고 분석만 작업 ID 방식입니다. 로컬 모델 과부하를 줄이기 위해 AI/검색 작업을 단일 작업자로 순차 처리하므로 긴 수집 작업 중 검색은 대기할 수 있습니다.

| 파일 | 책임 |
| --- | --- |
| `server.py` | HTTP, 자막/오디오/Whisper, 작업 제출 |
| `workflows.py` | 두 LangGraph, 분기, 체크포인트, 추천 규칙 |
| `domain.py` | JSON Schema/Pydantic, 정규화, 품질 검사, 시맨틱 레이어 |
| `storage.py` | SQLite 스키마·저장·조회·작업 상태 |
| `integrations.py` | 로컬 Ollama 생성/임베딩, Weaviate v4 클라이언트 |
| `health.py` | 서비스별 읽기 전용 준비 상태 검사 |
| `app.js`, `index.html`, `styles.css` | 진행 상황, 확인 UI, SQL 목록, 검색 필터 |
| `compose.yaml` | 로컬 Weaviate 인프라 |
| `tests/test_workflows.py` | 실제 LangGraph/SQLite + 외부 연동 대역 테스트 |
| `tests/test_http.py` | 실제 HTTP 서버의 비동기 분석·조회·검색·비공개 파일 차단 테스트 |

설정값: `OLLAMA_URL`(기본 `http://127.0.0.1:11434`), `OLLAMA_MODEL`, `EMBEDDING_MODEL`, `WHISPER_MODEL`(base), `WEAVIATE_HOST`(127.0.0.1), `WEAVIATE_HTTP_PORT`(8080), `WEAVIATE_GRPC_PORT`(50051), `WEAVIATE_COLLECTION`(RecipeV1).

## 7. 검증·백업·운영 한계

```powershell
.\.venv-graph\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv-graph\Scripts\python.exe -X utf8 -m pip check
```

Python/HTTP 자동 테스트 **19개 통과**, 패키지 의존성 검사 통과, JavaScript 문법 검사 통과를 확인했습니다. DOM 테스트에서도 저장 목록·상세 열기, HTML 이스케이프, 재색인, 냉장고 저장, 검색 필터, 잘못된 확인 JSON 차단, 확인 후 재개, 인덱스 실패 시 원본 저장 안내, 서비스 상태 표시를 검증했습니다. DOM 검증은 실제 브라우저의 화면 배치·터치 조작 검증과 다릅니다.

DOM 테스트 재현 (Node 20.19+ 또는 패키지에 포함된 Node 사용):

```powershell
# Node/npm이 PATH에 있는 경우
npm install --prefix .runtime/ui-test --no-audit --no-fund jsdom@27
node tests/test_ui.cjs
```

이 프로젝트의 Python 환경에 설치된 Node 실행 파일은 `.venv-graph\Lib\site-packages\nodejs_wheel\node.exe`입니다. 앱 실행에는 별도 Node 명령을 입력할 필요가 없습니다.

테스트는 실제 LangGraph와 임시 SQLite를 사용하고, 모델/YouTube/Weaviate는 대역을 사용합니다. 정상 저장·중복·재시작·확인 후 재개·재검토 횟수 제한·인덱스 실패와 복구·정확한 재료 매칭·조건 필터를 검사합니다. 테스트 통과가 특정 YouTube 영상 수집 성공이나 실제 모델 추론 품질을 보장하지는 않습니다.

실제 Ollama JSON 생성(품질 검사 통과)·768차원 임베딩을 검증했습니다. 실제 LLM을 사용하는 LangGraph → 임시 SQLite 저장 → 냉장고 재료 100% 일치 추천도 통과했고, Weaviate 미실행 시 경고와 원본 보존을 확인했습니다. 이전에 제공한 영상 `UUOpe_sTKzA`에서 한국어 자동 자막 6,282자 추출과 오디오 스트림 조회가 성공했습니다. 연결 가능한 브라우저가 없어 실제 화면 클릭 검증은 수행하지 못했습니다. Weaviate 실서버 검증은 위 BIOS 설정 때문에 아직 완료되지 않았습니다.

같은 영상에서 **오디오 다운로드 → 로컬 Whisper base(CPU/int8) → 한국어 텍스트 10,468자 생성**도 실제 검증했습니다. 다운로드한 임시 오디오는 정상 삭제되었고 Whisper 모델 캐시만 남았습니다. CPU에서는 수 분이 걸렸습니다. 글자 수는 실행 성공 기록일 뿐 인식 정확도 지표가 아닙니다. 자막과 Whisper의 표현·분량이 다를 수 있으며 재료/수량은 사용자 확인이 필요할 수 있습니다.

실제 서비스 통합 검증 명령 (API 키 사용 안 함, 테스트용 임시 SQL 사용):

```powershell
.\.venv-graph\Scripts\python.exe -X utf8 tests/live_check.py --ollama
.\.venv-graph\Scripts\python.exe -X utf8 tests/live_check.py --workflow
# Docker/Weaviate 준비 후 실행
.\.venv-graph\Scripts\python.exe -X utf8 tests/live_check.py --weaviate
```

Weaviate 테스트는 매번 고유한 `RecipeTest...` 컬렉션을 만들고 해당 테스트 컬렉션만 지웁니다. 사용자 `RecipeV1` 데이터는 건드리지 않습니다. `--workflow`가 완료되더라도 출력의 `weaviate_indexed`가 false이면 SQL/폴백 추천만 성공한 것이므로 전체 의미 검색 성공과 구분하세요.

수동 점검 순서:

1. Ollama와 임베딩 모델, Docker Weaviate 준비 상태 확인.
2. 텍스트에 ‘달걀 2개를 프라이팬에 익혀요’를 입력해 분석. 필요하면 확인 화면에서 편집·승인.
3. SQLite 저장과 인덱스 `indexed` 확인. 같은 텍스트로 중복 저장되지 않는지 확인.
4. 앱 재시작 후 목록에서 상세 레시피를 다시 열기.
5. 냉장고에 ‘계란’ 추가 → ‘달걀’로 정규화되어 일치하는지 확인.
6. Weaviate를 멈춰도 기존 원본 조회/재료 추천이 가능한지 확인. 복구 후 재색인.
7. 마지막으로 YouTube URL 수집 확인. 차단되면 수집 문제이며 SQLite/LLM 오류와 구분.

백업은 서버를 정상 종료한 뒤 `data/` 전체를 복사하는 방식이 간단합니다. WAL 모드이므로 실행 중 `.db` 파일만 복사하지 마세요. 검색 인덱스는 원본에서 다시 만들 수 있지만 체크포인트·원문은 SQL 백업이 필요합니다. DB, 체크포인트, 임시 음성은 Git에서 제외하고 HTTP로도 노출하지 않습니다.

현재는 인증·사용자별 격리·공유·동기화·휴대폰 네이티브 실행이 없는 **개인 PC용 MVP**입니다. 모든 포트는 루프백에 바인딩됩니다. 익명 Weaviate 포트를 인터넷에 공개하지 마세요. 공개 배포에는 인증·권한·요청 제한·정식 앱 서버·백업 정책을 추가해야 합니다. 휴대폰 자체에 저장하려면 모바일 SQLite와 별도의 온디바이스 모델 런타임이 필요하며, 현재 PC Ollama/Weaviate 구성이 자동으로 휴대폰에서 실행되지는 않습니다.

### 참고한 공식 문서

- [LangGraph 워크플로와 에이전트](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- [LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Weaviate Docker 설치](https://docs.weaviate.io/deploy/installation-guides/docker-installation)
- [Weaviate 로컬 시작](https://docs.weaviate.io/weaviate/quickstart/local)
- [Ollama 임베딩 API](https://docs.ollama.com/api/embed)
- [pytubefix 사용법](https://pytubefix.readthedocs.io/en/latest/user/quickstart.html)
