"""SQLite persistence behind a small repository interface.

Swap for Supabase Postgres by re-implementing this class against the schema in docs/schema.sql;
the API and graph never touch SQL directly.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS research_jobs (
  id TEXT PRIMARY KEY, name TEXT, input_url TEXT, user_note TEXT, status TEXT NOT NULL,
  error TEXT, model_config TEXT, created_at TEXT, updated_at TEXT, result_json TEXT
);
CREATE TABLE IF NOT EXISTS job_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES research_jobs(id) ON DELETE CASCADE,
  stage TEXT, event_type TEXT, message TEXT, timestamp TEXT, metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_job ON job_events(job_id);
CREATE TABLE IF NOT EXISTS voice_profiles (id TEXT PRIMARY KEY, preferences_json TEXT, updated_at TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._lock = threading.Lock()

    def _exec(self, sql: str, args: tuple = ()):
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur

    def create_job(self, input_url: str | None, user_note: str, model_config: dict) -> str:
        jid = uuid.uuid4().hex[:12]
        self._exec("INSERT INTO research_jobs(id,name,input_url,user_note,status,model_config,created_at,updated_at)"
                   " VALUES (?,?,?,?,?,?,?,?)",
                   (jid, input_url or "Pasted content", input_url, user_note, "queued", json.dumps(model_config), now(), now()))
        return jid

    def add_event(self, job_id: str, e) -> None:
        self._exec("INSERT INTO job_events(job_id,stage,event_type,message,timestamp,metadata) VALUES (?,?,?,?,?,?)",
                   (job_id, e.stage, e.event_type, e.message, e.timestamp.isoformat(), json.dumps(e.metadata)))

    def set_status(self, job_id: str, status: str, error: str | None = None) -> None:
        self._exec("UPDATE research_jobs SET status=?, error=?, updated_at=? WHERE id=?", (status, error, now(), job_id))

    def save_result(self, job_id: str, status: str, error: str | None, result: dict) -> None:
        self._exec("UPDATE research_jobs SET status=?, error=?, result_json=?, updated_at=? WHERE id=?",
                   (status, error, json.dumps(result, default=str), now(), job_id))

    def get_job(self, job_id: str) -> dict | None:
        row = self._exec("SELECT * FROM research_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["result"] = json.loads(d.pop("result_json")) if d.get("result_json") else None
        d["model_config"] = json.loads(d["model_config"] or "{}")
        return d

    def list_jobs(self) -> list[dict]:
        rows = self._exec("SELECT id,name,input_url,status,created_at,updated_at FROM research_jobs "
                          "ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def events(self, job_id: str) -> list[dict]:
        rows = self._exec("SELECT stage,event_type,message,timestamp,metadata FROM job_events WHERE job_id=? ORDER BY id",
                          (job_id,)).fetchall()
        return [{**dict(r), "metadata": json.loads(r["metadata"] or "{}")} for r in rows]

    def rename(self, job_id: str, name: str) -> bool:
        return self._exec("UPDATE research_jobs SET name=?, updated_at=? WHERE id=?", (name[:200], now(), job_id)).rowcount > 0

    def delete(self, job_id: str) -> bool:  # events cascade: full deletion, no residual data
        return self._exec("DELETE FROM research_jobs WHERE id=?", (job_id,)).rowcount > 0

    def get_voice(self) -> dict:
        row = self._exec("SELECT preferences_json FROM voice_profiles WHERE id='default'").fetchone()
        return json.loads(row[0]) if row else {"style_rules": [], "example_texts": []}

    def set_voice(self, prefs: dict) -> None:
        self._exec("INSERT INTO voice_profiles(id,preferences_json,updated_at) VALUES('default',?,?) "
                   "ON CONFLICT(id) DO UPDATE SET preferences_json=excluded.preferences_json, updated_at=excluded.updated_at",
                   (json.dumps(prefs), now()))
