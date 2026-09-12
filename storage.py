"""SQLite is authoritative; search indexes can always be rebuilt."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

class Store:
    def __init__(self, path):
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
    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()
    def unpack(self, row):
        if row is None: return None
        data = dict(row)
        for key in ('recipe', 'semantic'): data[key] = json.loads(data[key])
        return data
    def all(self):
        with self.connect() as db:
            return [self.unpack(x) for x in db.execute('SELECT * FROM recipes ORDER BY created_at DESC, id')]
    def get(self, id):
        with self.connect() as db:
            return self.unpack(db.execute('SELECT * FROM recipes WHERE id=?', (id,)).fetchone())
    def find(self, key):
        with self.connect() as db:
            return self.unpack(db.execute('SELECT * FROM recipes WHERE source_key=?', (key,)).fetchone())
    def save(self, id, key, url, transcript, recipe, semantic, model):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO recipes(id,source_key,source_url,transcript,recipe,semantic,model) VALUES(?,?,?,?,?,?,?)',
                       (id,key,url,transcript,json.dumps(recipe,ensure_ascii=False),json.dumps(semantic,ensure_ascii=False),model))
        return self.find(key)
    def indexed(self, id, status, error=None):
        with self.connect() as db:
            db.execute('UPDATE recipes SET index_status=?, index_error=? WHERE id=?', (status,error,id))
    def pantry(self, items=None):
        with self.connect() as db:
            if items is not None:
                db.execute('DELETE FROM pantry')
                db.executemany('INSERT OR IGNORE INTO pantry VALUES(?)', [(x,) for x in items])
            return [x['name'] for x in db.execute('SELECT name FROM pantry ORDER BY name')]
    def job(self, id, **changes):
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
    r = row['recipe']
    return {**r, 'id': row['id'], 'source': row['source_url'],
            'ingredient_details': r['ingredients'],
            'ingredients': [' '.join(str(v) for v in (x['name'],x['quantity'],x['unit']) if v is not None) for x in r['ingredients']],
            'semantic': row['semantic'], 'index_status': row['index_status'],
            'palette': ['#c05b3e','#efaa62','#733a2d'], 'emoji': '🍳'}
