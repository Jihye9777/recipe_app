"""원본을 읽기 전용으로 비교하는 로컬 모델 평가. 출력은 격리된 .runtime에 보관한다."""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations import Ollama, QdrantIndex
from storage import Store
from workflows import Pipelines

SAMPLE = '식초 1.5스푼을 그릇에 넣고 섞어요.\n달걀 1개를 물에 넣고 전자레인지에서 1분 30초 익혀요.'


def read_cases(path, video_id=None):
    """지정 SQLite 원본을 mode=ro로 읽어 평가 행을 반환한다. 미존재·SQL 오류는 전파한다."""
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        db.row_factory = sqlite3.Row
        if video_id:
            rows = db.execute('SELECT id,source_url,transcript,recipe FROM recipes WHERE source_key=?', ('youtube:' + video_id,)).fetchall()
        else:
            rows = db.execute('SELECT id,source_url,transcript,recipe FROM recipes ORDER BY id LIMIT 3').fetchall()
        return [dict(row) for row in rows]
    finally:
        db.close()


def snapshot(rows):
    """원본 행 비교용 해시를 반환하며 원문을 로그로 출력하지 않는다."""
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def refuse_extraction(url):
    """평가 원문 외 URL 수집을 금지한다. 모든 입력에 RuntimeError를 발생시킨다."""
    raise RuntimeError('평가 원문만 사용합니다.')


def main():
    """명령행 입력을 별도 저장소에서 분석해 JSON 결과 경로·상태만 출력한다.

    --source-db는 읽기 전용이다. 생략하면 합성 예문을 사용한다. 모델·HTTP
    오류와 원본 변경은 실패로 보고한다. 평가 폴더를 자동 삭제하지 않는다.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-db', type=Path)
    parser.add_argument('--video-id')
    parser.add_argument('--ollama-url', default='http://127.0.0.1:11434')
    args = parser.parse_args()
    if urlparse(args.ollama_url).hostname not in {'127.0.0.1', 'localhost', '::1'}:
        parser.error('평가는 loopback 로컬 Ollama만 사용합니다.')
    cases = read_cases(args.source_db, args.video_id) if args.source_db else [
        {'id': 'synthetic', 'source_url': '', 'transcript': SAMPLE, 'recipe': '{}'}]
    if not cases: parser.error('평가할 원본 레시피가 없습니다.')
    original_hash = snapshot(cases)
    root = Path(__file__).resolve().parents[1] / '.runtime' / ('step-quality-eval-' + uuid.uuid4().hex)
    root.mkdir(parents=True)
    os.environ['NO_PROXY'] = '127.0.0.1,localhost,::1'
    llm = Ollama(); llm.url = args.ollama_url.rstrip('/')
    store = Store(root / 'recipe.db'); index = QdrantIndex(llm, root / 'qdrant')
    graph = Pipelines(store, llm, index, refuse_extraction, str(root / 'checkpoints.db'))
    results = []
    try:
        for case in cases:
            job_id = str(uuid.uuid4())
            graph.run(job_id, {'url': case['source_url'], 'text': case['transcript']})
            job = store.job(job_id)
            state = graph.ingest.get_state({'configurable': {'thread_id': job_id}}).values
            results.append({'case_id': case['id'], 'status': job['status'],
                'source_facts_present': bool(state.get('source_facts')),
                'source_issue_count': len(state.get('source_issues', [])),
                'review_issue_count': len((job.get('result') or {}).get('issues', [])),
                'saved': bool(state.get('row')), 'error': job.get('error')})
            print(json.dumps({'case': len(results), 'status': job['status']}, ensure_ascii=False), flush=True)
    finally:
        graph.checkpoint_db.close(); index.close()
    unchanged = not args.source_db or snapshot(read_cases(args.source_db, args.video_id)) == original_hash
    report = {'model': llm.model, 'source_unchanged': unchanged,
              'input': 'stored_transcript' if args.source_db else 'synthetic',
              'not_video_refetch': True, 'cases': results}
    report_path = root / 'report.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(report_path), 'source_unchanged': unchanged}, ensure_ascii=False), flush=True)
    return 0 if unchanged and all(row['status'] in {'complete', 'review'} for row in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
