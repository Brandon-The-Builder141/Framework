"""SQLite state; private conversations never feed public prayers."""
import json
import sqlite3
import time
import re
from pathlib import Path
from contextlib import closing


class Store:
    def __init__(self, path):
        self.path = Path(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA secure_delete=ON;
            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY, uid TEXT NOT NULL, role TEXT, content TEXT);
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY, uid TEXT NOT NULL, content TEXT);
            CREATE TABLE IF NOT EXISTS summaries (uid TEXT PRIMARY KEY, content TEXT);
            CREATE TABLE IF NOT EXISTS prayers (
                slot TEXT PRIMARY KEY, state TEXT, message_id TEXT, detail TEXT);
            CREATE TABLE IF NOT EXISTS requests (
                uid TEXT PRIMARY KEY, content TEXT, expires REAL);
            CREATE TABLE IF NOT EXISTS outreach (
                id INTEGER PRIMARY KEY, owner TEXT, target TEXT, sent REAL);
        ''')
        columns = {r[1] for r in self.db.execute('PRAGMA table_info(turns)')}
        needs_index = not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='turn_search'").fetchone()
        if 'created_at' not in columns:
            self.db.execute('ALTER TABLE turns ADD COLUMN created_at REAL')
        if 'source_id' not in columns:
            self.db.execute('ALTER TABLE turns ADD COLUMN source_id TEXT')
        self.db.executescript('''
            CREATE INDEX IF NOT EXISTS turns_user ON turns(uid,id);
            CREATE UNIQUE INDEX IF NOT EXISTS turns_source ON turns(source_id) WHERE source_id IS NOT NULL;
            CREATE TABLE IF NOT EXISTS embeddings(turn_id INTEGER PRIMARY KEY, vector TEXT);
            CREATE TABLE IF NOT EXISTS plans(uid TEXT PRIMARY KEY, content TEXT NOT NULL);
            CREATE VIRTUAL TABLE IF NOT EXISTS turn_search USING fts5(content, content='turns', content_rowid='id');
            CREATE TRIGGER IF NOT EXISTS turns_ai AFTER INSERT ON turns BEGIN
              INSERT INTO turn_search(rowid,content) VALUES(new.id,new.content); END;
            CREATE TRIGGER IF NOT EXISTS turns_ad AFTER DELETE ON turns BEGIN
              INSERT INTO turn_search(turn_search,rowid,content) VALUES('delete',old.id,old.content);
              DELETE FROM embeddings WHERE turn_id=old.id; END;
        ''')
        if needs_index:
            self.db.execute("INSERT INTO turn_search(turn_search) VALUES('rebuild')")
        self.db.commit()

    def history(self, uid):
        rows = self.db.execute("SELECT role, content FROM turns WHERE uid=? ORDER BY id DESC LIMIT 24", (str(uid),)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def remember_turn(self, uid, user, reply):
        with self.db:
            self.db.executemany("INSERT INTO turns(uid,role,content,created_at) VALUES(?,?,?,?)",
                                [(str(uid), "user", user, time.time()), (str(uid), "assistant", reply, time.time())])

    def archive(self, uid, role, text, source_id=None):
        with self.db:
            cursor = self.db.execute('INSERT OR IGNORE INTO turns(uid,role,content,created_at,source_id) VALUES(?,?,?,?,?)',
                                   (str(uid), role, text, time.time(),str(source_id) if source_id else None))
            return cursor.lastrowid if cursor.rowcount else None

    def retrieve(self, uid, query, vector=None):
        """Every search is scoped to one user; original messages are the evidence."""
        uid = str(uid)
        if re.search(r'\b(first|earliest|original)\b.*\b(conversation|talk|message|told|tell|said|thing)\b', query, re.I):
            return [{**dict(r),'content':r['content'][:1800]} for r in self.db.execute('SELECT * FROM turns WHERE uid=? ORDER BY id LIMIT 4', (uid,))]
        stop = set('the and that this with what when were have about remember told said you your our can did does how for from was'.split())
        words = [w for w in re.findall(r'\w+', query.lower()) if len(w)>2 and w not in stop][:24]
        found = {}
        relevance = {}
        if words:
            match = ' OR '.join('"'+w+'"' for w in words)
            for r in self.db.execute('SELECT t.* FROM turn_search JOIN turns t ON t.id=turn_search.rowid WHERE turn_search MATCH ? AND t.uid=? AND t.role=\'user\' ORDER BY rank LIMIT 6', (match,uid)):
                found[r['id']] = dict(r)
                relevance[r['id']] = 1/(1+len(relevance))
        # Include recent lexical evidence even when relevance ranking favors old text.
        if words:
            for r in self.db.execute("SELECT t.* FROM turn_search JOIN turns t ON t.id=turn_search.rowid WHERE turn_search MATCH ? AND t.uid=? AND t.role='user' ORDER BY t.id DESC LIMIT 2",(match,uid)):
                found[r['id']]=dict(r)
                relevance.setdefault(r['id'],0)
        if vector:
            import math
            ranked = []
            for r in self.db.execute('SELECT t.*,e.vector FROM turns t JOIN embeddings e ON e.turn_id=t.id WHERE t.uid=? AND t.role=\'user\'', (uid,)):
                other = json.loads(r['vector'])
                if len(other) != len(vector):
                    continue
                score = sum(a*b for a,b in zip(vector,other))/(math.sqrt(sum(a*a for a in vector)*sum(b*b for b in other)) or 1)
                if score >= .55:
                    ranked.append((score,dict(r)))
            for score, r in sorted(ranked,key=lambda v:v[0],reverse=True)[:4]:
                r.pop('vector',None)
                found[r['id']] = r
                relevance[r['id']] = relevance.get(r['id'],0)+score
        # Keep strong old matches rather than discarding them solely for age.
        selected = sorted(found.values(),key=lambda r:relevance[r['id']],reverse=True)[:6]
        selected_ids = {r['id'] for r in selected}
        # Reserve room for newer matching statements, including corrections.
        selected += sorted((r for r in found.values() if r['id'] not in selected_ids),key=lambda r:r['id'],reverse=True)[:2]
        result = sorted(selected,key=lambda r:r['id'])
        return [{**r, 'content':r['content'][:900]} for r in result]

    def unembedded(self, uid, limit=24):
        return self.db.execute('SELECT id,content FROM turns WHERE uid=? AND role=\'user\' AND id NOT IN (SELECT turn_id FROM embeddings) ORDER BY id LIMIT ?', (str(uid),limit)).fetchall()

    def save_vectors(self, rows, vectors):
        with self.db:
            self.db.executemany('INSERT OR REPLACE INTO embeddings VALUES(?,?)', [(r['id'],json.dumps(v)) for r,v in zip(rows,vectors)])

    def plan(self, uid):
        row = self.db.execute('SELECT content FROM plans WHERE uid=?',(str(uid),)).fetchone()
        return json.loads(row[0]) if row else None

    def save_plan(self, uid, plan):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO plans VALUES(?,?)',(str(uid),json.dumps(plan)))

    def profile(self, uid):
        notes = [r[0] for r in self.db.execute("SELECT content FROM notes WHERE uid=? ORDER BY id DESC LIMIT 20", (str(uid),))]
        row = self.db.execute("SELECT content FROM summaries WHERE uid=?", (str(uid),)).fetchone()
        return {"notes": notes, "conversation_summary": row[0] if row else ""}

    def summarize(self, uid, content):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO summaries VALUES(?,?)", (str(uid), content[:4000]))

    def note(self, uid, content):
        with self.db:
            self.db.execute("INSERT INTO notes(uid,content) VALUES(?,?)", (str(uid), content[:1000]))

    def forget(self, uid):
        with self.db:
            for table in ("turns", "notes", "summaries", "requests", "plans"):
                self.db.execute(f"DELETE FROM {table} WHERE uid=?", (str(uid),))
        # Also remove this user's data from every backup managed by this application.
        for path in self.path.parent.glob('backups/ray-*.sqlite3'):
            with closing(sqlite3.connect(path)) as backup, backup:
                backup.execute('PRAGMA secure_delete=ON')
                for table in ('turns','notes','summaries','requests','plans'):
                    backup.execute(f'DELETE FROM {table} WHERE uid=?',(str(uid),))

    def backup(self):
        folder = self.path.parent/'backups'
        folder.mkdir(exist_ok=True)
        target = folder/('ray-'+time.strftime('%Y-%m-%d')+'.sqlite3')
        if not target.exists():
            with closing(sqlite3.connect(target)) as backup:
                self.db.backup(backup)
        for old in sorted(folder.glob('ray-*.sqlite3'))[:-14]:
            old.unlink()

    def share_request(self, uid, content):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO requests VALUES(?,?,?)", (str(uid), content[:800], time.time() + 7*86400))

    def public_requests(self):
        return [r[0] for r in self.db.execute("SELECT content FROM requests WHERE expires>?", (time.time(),))]

    def claim_prayer(self, slot):
        # Claim before sending: ambiguous delivery is not retried automatically.
        with self.db:
            cur = self.db.execute("INSERT OR IGNORE INTO prayers VALUES(?, 'claimed', NULL, '')", (slot,))
            return cur.rowcount == 1

    def prayer_result(self, slot, state, message_id="", detail=""):
        with self.db:
            self.db.execute("UPDATE prayers SET state=?,message_id=?,detail=? WHERE slot=?", (state, str(message_id), detail, slot))

    def last_prayer(self):
        row = self.db.execute("SELECT slot,state FROM prayers ORDER BY slot DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def close(self):
        self.db.close()
