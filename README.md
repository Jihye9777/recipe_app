# 한입노트 — 로컬 레시피 북

YouTube URL 또는 직접 붙여 넣은 텍스트를 레시피로 정리하고, 냉장고 재료로 검색·추천하는 개인용 로컬 웹 앱입니다.

- **SQLite**: 유일한 원본 저장소
- **Qdrant Local**: 원본에서 다시 만들 수 있는 벡터 검색 인덱스
- **시맨틱 레이어**: 근거와 버전을 가진 파생 정보
- **LangGraph**: 정해진 노드와 조건 분기로 두 파이프라인 실행

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

기본 생성 모델은 `gemma4:latest`, 임베딩 모델은 `embeddinggemma`입니다. 설치된 이름이 다르면 앱을 실행할 터미널에서 설정합니다.

```powershell
$env:OLLAMA_MODEL = "gemma4:latest"
$env:EMBEDDING_MODEL = "embeddinggemma"
```

생성과 임베딩 모두 로컬 Ollama만 사용하며 유료 API로 자동 전환하지 않습니다. 앱 실행:

```powershell
.\.venv-graph\Scripts\python.exe -X utf8 -u server.py
```

또는 `start_graph.bat`을 더블클릭하고 [http://localhost:8000](http://localhost:8000)을 엽니다. Qdrant는 `data/qdrant/`에서 앱과 함께 실행되므로 별도 포트나 실행 명령이 없습니다.

## 3. 파이프라인 1 — 수집·저장

```text
YouTube URL / 직접 입력 텍스트
 → URL 검증·중복 확인
 → youtube-transcript-api
    └ 실패 시 pytubefix 오디오 다운로드 → Local Whisper
 → 자막 전처리
 → Ollama 구조화 → Pydantic JSON Schema 검증
 → 재료명·단위 정규화 → 품질 검사
    └ 불확실하면 LLM 재검토 1회 또는 사용자 확인
 → SQLite 원본·시맨틱 데이터 저장
 → Ollama 임베딩 → Qdrant Local upsert
```

실제 그래프는 `workflows.py`의 `Pipelines.ingest`입니다. yt-dlp는 사용하지 않습니다. 자막과 오디오 다운로드가 모두 차단되면 직접 텍스트 붙여넣기를 사용할 수 있습니다. 원문과 구조화 결과를 함께 저장하고, 모르는 수량이나 시간은 임의로 만들지 않고 `null`로 둡니다.

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

임베딩 모델을 변경할 때는 기존 벡터와 섞지 말고 새 컬렉션을 사용한 뒤 전체 재색인합니다.

```powershell
$env:EMBEDDING_MODEL = "새_임베딩_모델"
$env:QDRANT_COLLECTION = "RecipeV2"
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

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama 주소 |
| `OLLAMA_MODEL` | `gemma4:latest` | 구조화·팁 모델 |
| `EMBEDDING_MODEL` | `embeddinggemma` | 임베딩 모델 |
| `WHISPER_MODEL` | `base` | 음성 인식 모델 |
| `QDRANT_PATH` | `data/qdrant` | Qdrant 저장 폴더 |
| `QDRANT_COLLECTION` | `RecipeV1` | 벡터 컬렉션 |

## 7. API와 코드 위치

| 경로 | 용도 |
| --- | --- |
| `GET /api/recipes` | 레시피 목록·상세 |
| `GET/POST /api/pantry` | 냉장고 읽기·저장 |
| `POST /api/analyze` | URL 또는 텍스트 분석 시작 |
| `GET /api/jobs/<id>` | 작업 상태 조회 |
| `POST /api/review`, `POST /api/retry` | 확인·재개 |
| `POST /api/search` | 재료·자연어·조건 검색 |
| `POST /api/reindex` | 한 건 재색인 |
| `POST /api/reindex-all` | 필요한 모든 레시피 재색인 |
| `GET /api/health` | SQLite·Ollama·임베딩·Qdrant 상태 |

`server.py`는 HTTP와 수집, `workflows.py`는 LangGraph, `domain.py`는 스키마·시맨틱 규칙, `storage.py`는 SQLite, `integrations.py`는 Ollama·Qdrant 연동을 담당합니다.

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
