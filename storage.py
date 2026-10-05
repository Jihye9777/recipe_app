"""SQLite is authoritative; search indexes can always be rebuilt."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

class Store:
    """SQLite 원본 DB와 작업 상태에 접근하는 저장소.

    각 공개 메서드는 필요한 시점에 짧은 연결을 열고 닫는다. 레시피 JSON과
    시맨틱 JSON은 읽을 때 Python 사전으로 역직렬화된다.
    """

    def __init__(self, path):
        """DB 경로를 준비하고 현재 스키마 및 이전 버전 마이그레이션을 적용한다.

        Args:
            path: SQLite 파일 경로. ``str`` 또는 ``pathlib.Path``를 허용한다.

        Side Effects:
            부모 폴더와 DB 파일을 만들 수 있으며 WAL 모드를 활성화한다.
            누락된 ``jobs.payload``, ``recipes.index_backend``,
            ``recipes.embedding_model`` 열을 기존 DB에 추가한다.
        """
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS recipes(
                id TEXT PRIMARY KEY, source_key TEXT UNIQUE NOT NULL,
                source_url TEXT NOT NULL, transcript TEXT NOT NULL,
                recipe TEXT NOT NULL, semantic TEXT NOT NULL,
                model TEXT NOT NULL, index_status TEXT NOT NULL DEFAULT 'pending',
                index_error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS pantry(name TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY, status TEXT NOT NULL, stage TEXT,
                result TEXT, error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            ''')
            if 'payload' not in {x['name'] for x in db.execute('PRAGMA table_info(jobs)')}:
                db.execute('ALTER TABLE jobs ADD COLUMN payload TEXT')
            recipe_columns={x['name'] for x in db.execute('PRAGMA table_info(recipes)')}
            if 'index_backend' not in recipe_columns:
                db.execute('ALTER TABLE recipes ADD COLUMN index_backend TEXT')
            if 'embedding_model' not in recipe_columns:
                db.execute('ALTER TABLE recipes ADD COLUMN embedding_model TEXT')
    @contextmanager
    def connect(self):
        """트랜잭션과 종료를 자동 관리하는 SQLite 연결을 제공한다.

        Yields:
            행을 ``sqlite3.Row``로 반환하도록 설정된 ``sqlite3.Connection``.

        Raises:
            sqlite3.Error: 연결, SQL 실행 또는 커밋에 실패했을 때. 예외가
                발생하면 컨텍스트 관리자가 트랜잭션을 롤백하고 연결을 닫는다.
        """
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()
    def unpack(self, row):
        """SQLite 행의 JSON 열을 Python 값으로 변환한다.

        Args:
            row: ``recipes`` 조회 결과인 ``sqlite3.Row`` 또는 ``None``.

        Returns:
            ``recipe``와 ``semantic``이 역직렬화된 사전. 입력이 ``None``이면
            ``None``을 반환한다.
        """
        if row is None: return None
        data = dict(row)
        for key in ('recipe', 'semantic'): data[key] = json.loads(data[key])
        return data
    def all(self):
        """저장된 모든 레시피를 최신순으로 조회한다.

        Returns:
            역직렬화된 레시피 행 사전 목록. DB가 비어 있으면 빈 목록이다.
        """
        with self.connect() as db:
            return [self.unpack(x) for x in db.execute('SELECT * FROM recipes ORDER BY created_at DESC, id')]
    def get(self, id):
        """UUID로 레시피 한 건을 조회한다.

        Args:
            id: ``recipes.id``에 저장된 레시피 UUID 문자열.

        Returns:
            역직렬화된 레시피 행 사전. 일치하는 행이 없으면 ``None``.
        """
        with self.connect() as db:
            return self.unpack(db.execute('SELECT * FROM recipes WHERE id=?', (id,)).fetchone())
    def find(self, key):
        """중복 판별 키로 레시피 한 건을 조회한다.

        Args:
            key: ``youtube:<video_id>``, ``text:<sha256>`` 또는
                ``legacy:<id>`` 형식의 고유 ``source_key``.

        Returns:
            역직렬화된 레시피 행 사전. 일치하는 행이 없으면 ``None``.
        """
        with self.connect() as db:
            return self.unpack(db.execute('SELECT * FROM recipes WHERE source_key=?', (key,)).fetchone())
    def save(self, id, key, url, transcript, recipe, semantic, model):
        """검증된 레시피 원본을 중복 없이 저장한다.

        Args:
            id: 결정적으로 생성한 레시피 UUID 문자열.
            key: 중복 방지용 고유 source key.
            url: 원본 YouTube URL. 직접 입력이면 빈 문자열일 수 있다.
            transcript: 추출 또는 직접 입력한 원문 전체.
            recipe: 검증·정규화된 레시피 사전.
            semantic: 버전형 시맨틱 파생 정보 사전.
            model: 구조화에 사용한 생성 모델 이름.

        Returns:
            저장된 행 또는 동일 ``key``로 먼저 존재하던 행의 역직렬화 사전.

        Side Effects:
            새 행의 벡터 상태는 기본값 ``pending``으로 기록된다.
        """
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO recipes(id,source_key,source_url,transcript,recipe,semantic,model) VALUES(?,?,?,?,?,?,?)',
                       (id,key,url,transcript,json.dumps(recipe,ensure_ascii=False),json.dumps(semantic,ensure_ascii=False),model))
        return self.find(key)
    def indexed(self, id, status, error=None, backend=None, embedding_model=None):
        """레시피의 검색 인덱스 처리 결과를 갱신한다.

        Args:
            id: 갱신할 레시피 UUID.
            status: ``pending``, ``indexed`` 또는 ``failed`` 상태 문자열.
            error: 실패 상세 메시지. 성공이면 ``None``.
            backend: 사용한 벡터 백엔드 이름(현재 ``qdrant-local``).
            embedding_model: 벡터를 생성한 Ollama 임베딩 모델 이름.

        Returns:
            반환값 없음.
        """
        with self.connect() as db:
            db.execute('UPDATE recipes SET index_status=?, index_error=?, index_backend=?, embedding_model=? WHERE id=?',
                       (status,error,backend,embedding_model,id))
    def needs_index(self, backend, embedding_model):
        """현재 벡터 구성으로 다시 색인해야 하는 레시피를 조회한다.

        Args:
            backend: 기대하는 인덱스 백엔드 이름.
            embedding_model: 기대하는 임베딩 모델 이름.

        Returns:
            상태가 ``indexed``가 아니거나 백엔드·모델이 다른 레시피 행 목록.
        """
        with self.connect() as db:
            rows=db.execute('SELECT * FROM recipes WHERE index_status != ? OR index_backend IS NOT ? OR embedding_model IS NOT ? ORDER BY created_at,id',
                            ('indexed',backend,embedding_model)).fetchall()
            return [self.unpack(x) for x in rows]
    def pantry(self, items=None):
        """냉장고 재료를 조회하거나 전체 교체한다.

        Args:
            items: 저장할 정규화된 재료명 iterable. ``None``이면 수정 없이
                현재 값만 조회한다. 빈 iterable이면 모든 재료를 삭제한다.

        Returns:
            DB에 저장된 재료명을 가나다/문자열 오름차순으로 정렬한 목록.

        Side Effects:
            ``items``가 주어지면 기존 pantry 행을 모두 지우고 새 목록을
            중복 없이 저장한다.
        """
        with self.connect() as db:
            if items is not None:
                db.execute('DELETE FROM pantry')
                db.executemany('INSERT OR IGNORE INTO pantry VALUES(?)', [(x,) for x in items])
            return [x['name'] for x in db.execute('SELECT name FROM pantry ORDER BY name')]
    def job(self, id, **changes):
        """비동기 분석 작업을 생성·부분 갱신하고 현재 상태를 반환한다.

        Args:
            id: 작업 UUID 문자열.
            **changes: 변경할 ``status``, ``stage``, ``result``, ``error``,
                ``payload`` 중 일부. ``result``와 ``payload``는 JSON으로 저장된다.

        Returns:
            ``result``와 ``payload``가 역직렬화된 작업 사전. 변경 없이 조회한
            ID가 존재하지 않으면 ``None``.

        Raises:
            ValueError: 허용 목록에 없는 필드를 갱신하려 할 때.
        """
        with self.connect() as db:
            if changes:
                db.execute("INSERT OR IGNORE INTO jobs(id,status) VALUES(?,'queued')", (id,))
                for key, value in changes.items():
                    if key not in {'status','stage','result','error','payload'}: raise ValueError(key)
                    if key in {'result','payload'}: value = json.dumps(value, ensure_ascii=False)
                    db.execute(f'UPDATE jobs SET {key}=? WHERE id=?', (value,id))
            row = db.execute('SELECT * FROM jobs WHERE id=?', (id,)).fetchone()
            if row is None: return None
            result = dict(row)
            result['result'] = json.loads(result['result']) if result['result'] else None
            result['payload'] = json.loads(result['payload']) if result['payload'] else None
            return result

def public(row):
    """내부 SQLite 행을 브라우저에 반환할 공개 레시피 형식으로 변환한다.

    Args:
        row: :meth:`Store.unpack`으로 변환된 레시피 행 사전.

    Returns:
        구조화 레시피 필드에 ID, 출처, 상세/표시용 재료, 시맨틱 데이터,
        인덱스 상태와 UI 장식 값을 합친 새 사전. 원본 행은 수정하지 않는다.
    """
    r = row['recipe']
    return {**r, 'id': row['id'], 'source': row['source_url'],
            'ingredient_details': r['ingredients'],
            'ingredients': [' '.join(str(v) for v in (x['name'],x['quantity'],x['unit']) if v is not None) for x in r['ingredients']],
            'semantic': row['semantic'], 'index_status': row['index_status'],
            'index_backend': row.get('index_backend'), 'embedding_model': row.get('embedding_model'),
            'palette': ['#c05b3e','#efaa62','#733a2d'], 'emoji': '🍳'}
