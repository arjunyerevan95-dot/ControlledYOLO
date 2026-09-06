"""Local state and the documented Codex hook contract. Standard library only."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

VERSION = "2.0.0"
SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
LOCAL_TOOLS = {"Bash", "apply_patch"}
EVENTS = {"SessionStart", "SessionEnd", "PermissionRequest", "PostToolUse", "Stop", "Interrupt"}
DEFAULTS = {"paused": False, "chime_seconds": 10, "push_seconds": 120,
            "ntfy_url": "", "ntfy_token": "", "visible_monitor": True}


def state_home() -> Path:
    override = os.environ.get("CONTROLLEDYOLO_HOME")
    return Path(override) if override else Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "ControlledYOLO/state"


def clean_label(value, fallback="Chat"):
    return " ".join(str(value or fallback).split())[:160]


class Store:
    def __init__(self, home=None, clock=time.time):
        self.home = Path(home) if home is not None else state_home()
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "state.sqlite3"
        self.clock = clock
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS chats(
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, selected INTEGER NOT NULL DEFAULT 0,
                    mode TEXT NOT NULL DEFAULT 'notify', expires REAL, last_seen REAL,
                    native_seen REAL, source TEXT NOT NULL DEFAULT 'manual');
                CREATE TABLE IF NOT EXISTS requests(
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                    tool TEXT NOT NULL, fingerprint TEXT NOT NULL, source TEXT NOT NULL,
                    status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                    acknowledged INTEGER NOT NULL DEFAULT 0, push_at REAL NOT NULL DEFAULT 0,
                    push_attempt REAL NOT NULL DEFAULT 0, push_error TEXT NOT NULL DEFAULT '');
                CREATE INDEX IF NOT EXISTS requests_session ON requests(session_id, status);
            """)
            for key, value in DEFAULTS.items():
                db.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (key, json.dumps(value)))

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _get(db, key, default=None):
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    @staticmethod
    def _set(db, key, value):
        db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))

    def get(self, key, default=None):
        with self.db() as db:
            return self._get(db, key, default)

    def set(self, key, value):
        with self.db() as db:
            self._set(db, key, value)

    def settings(self):
        with self.db() as db:
            return {r["key"]: json.loads(r["value"]) for r in db.execute("SELECT * FROM settings")}

    def upsert_chat(self, session, title=None, source="manual", native=False):
        if not isinstance(session, str) or not SESSION_ID.fullmatch(session):
            raise ValueError("Use the actual Codex chat ID, not the chat title.")
        now = self.clock()
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO chats(id,title,source) VALUES (?,?,?)",
                       (session, clean_label(title, session), source))
            if title:
                db.execute("UPDATE chats SET title=? WHERE id=?", (clean_label(title), session))
            if native:
                db.execute("UPDATE chats SET last_seen=?,native_seen=?,source='hook' WHERE id=?", (now, now, session))

    def configure_chat(self, session, selected, mode="notify", minutes=0):
        if mode not in {"notify", "auto_local"} or not 0 <= minutes <= 10080:
            raise ValueError("Invalid chat mode or expiry.")
        expires = self.clock() + minutes * 60 if minutes else None
        with self.db() as db:
            if not db.execute("SELECT 1 FROM chats WHERE id=?", (session,)).fetchone():
                raise ValueError("Unknown chat ID.")
            db.execute("UPDATE chats SET selected=?,mode=?,expires=? WHERE id=?",
                       (int(bool(selected)), mode, expires, session))

    def chats(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM chats ORDER BY selected DESC,title COLLATE NOCASE,id")]

    def heartbeat(self, owner):
        with self.db() as db:
            self._set(db, "heartbeat", {"owner": owner, "at": self.clock()})

    def stop_heartbeat(self, owner):
        with self.db() as db:
            if self._get(db, "heartbeat", {}).get("owner") == owner:
                self._set(db, "heartbeat", {})

    def _active(self, db, session, now):
        row = db.execute("SELECT * FROM chats WHERE id=?", (session,)).fetchone()
        return row if row and row["selected"] and (row["expires"] is None or row["expires"] > now) else None

    def handle_hook(self, event):
        if not isinstance(event, dict) or event.get("hook_event_name") not in EVENTS:
            return {}
        session = event.get("session_id")
        if not isinstance(session, str) or not SESSION_ID.fullmatch(session):
            return {}
        kind = event["hook_event_name"]
        self.upsert_chat(session, source="hook", native=True)
        turn = str(event.get("turn_id") or "")[:200]
        tool = str(event.get("tool_name") or "Unknown tool")[:200]
        payload = json.dumps(event.get("tool_input"), sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        now = self.clock()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._set(db, "native_event_at", now)
            chat = self._active(db, session, now)
            if kind == "PermissionRequest":
                if not chat:
                    return {}
                hb = self._get(db, "heartbeat", {})
                heartbeat_age = now - hb.get("at", 0)
                active = not self._get(db, "paused", True) and 0 <= heartbeat_age < 12
                # Only the documented local-tool approval contract. Other prompts remain native.
                allow = active and chat["mode"] == "auto_local" and tool in LOCAL_TOOLS and bool(turn)
                status = "allowed_by_hook" if allow else "pending"
                db.execute("INSERT INTO requests(id,session_id,turn_id,tool,fingerprint,source,status,created,updated) VALUES (?,?,?,?,?,?,?,?,?)",
                           (uuid.uuid4().hex, session, turn, tool, fingerprint, "hook", status, now, now))
                if allow:
                    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
            elif kind == "PostToolUse" and turn:
                # One completion clears at most one matching request, including concurrent identical calls.
                row = db.execute("SELECT id FROM requests WHERE session_id=? AND turn_id=? AND tool=? AND fingerprint=? AND source='hook' AND status IN ('pending','allowed_by_hook') ORDER BY created,rowid LIMIT 1",
                                 (session, turn, tool, fingerprint)).fetchone()
                if row:
                    db.execute("UPDATE requests SET status='tool_finished',updated=? WHERE id=?", (now, row[0]))
            elif kind == "SessionEnd" or (kind in {"Stop", "Interrupt"} and turn):
                clause = "session_id=?" if kind == "SessionEnd" else "session_id=? AND turn_id=?"
                args = [session] if kind == "SessionEnd" else [session, turn]
                db.execute(f"UPDATE requests SET status=?,updated=? WHERE {clause} AND source='hook' AND status IN ('pending','allowed_by_hook')",
                           ["interrupted" if kind == "Interrupt" else "ended", now] + args)
        return {}

    def acknowledge(self, ids):
        with self.db() as db:
            db.executemany("UPDATE requests SET acknowledged=1,updated=? WHERE id=? AND status='pending'",
                           [(self.clock(), value) for value in ids])

    def requests(self, pending_only=False):
        with self.db() as db:
            query = "SELECT r.*,c.title,c.selected,c.expires FROM requests r JOIN chats c ON c.id=r.session_id"
            if pending_only:
                query += " WHERE r.status='pending'"
            return [dict(r) for r in db.execute(query + " ORDER BY r.created DESC" + ("" if pending_only else " LIMIT 500"))]

    def attention(self):
        now = self.clock()
        return [r for r in self.requests(True) if r["selected"] and not r["acknowledged"]
                and (r["expires"] is None or r["expires"] > now)]

    def update_push(self, request_id, success, error=""):
        with self.db() as db:
            db.execute("UPDATE requests SET push_attempt=?,push_at=CASE WHEN ? THEN ? ELSE push_at END,push_error=? WHERE id=?",
                       (self.clock(), bool(success), self.clock(), error[:200], request_id))

    def visible_snapshot(self, cards):
        """Read-only UI fallback. Its title-based observations never authorize an action."""
        now = self.clock()
        chats = self.chats()
        # Duplicate titles cannot identify a conversation. Ignore them.
        by_title = {}
        for chat in chats:
            by_title.setdefault(clean_label(chat["title"]).casefold(), []).append(chat)
        seen = {}
        with self.db() as db:
            previous = self._get(db, "visible_current", {})
            for card in cards:
                matches = by_title.get(clean_label(card.get("title")).casefold(), [])
                if len(matches) != 1 or not self._active(db, matches[0]["id"], now):
                    continue
                session = matches[0]["id"]
                # Native event evidence takes precedence for an outstanding request.
                if db.execute("SELECT 1 FROM requests WHERE session_id=? AND source='hook' AND status='pending'", (session,)).fetchone():
                    continue
                identity = hashlib.sha256((session + ":" + str(card.get("key", ""))).encode()).hexdigest()
                key = previous.get(identity) or "visible:" + uuid.uuid4().hex
                seen[identity] = key
                row = db.execute("SELECT status FROM requests WHERE id=?", (key,)).fetchone()
                if row and row[0] == "pending":
                    db.execute("UPDATE requests SET updated=? WHERE id=?", (now, key))
                else:
                    db.execute("INSERT OR REPLACE INTO requests(id,session_id,turn_id,tool,fingerprint,source,status,created,updated) VALUES (?,?,?,?,?,?,?,?,?)",
                               (key, session, "", "Visible permission card", "", "visible", "pending", now, now))
            # A hidden card is not proof of resolution: keep its reminder until acknowledgment.
            self._set(db, "visible_observed_at", now)
            self._set(db, "visible_count", len(seen))
            self._set(db, "visible_current", seen)

    def import_index(self, path):
        """Optional best-effort labels, never parsed as approval state or policy."""
        path = Path(path)
        if not path.exists():
            return 0
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            start = max(0, size - 8_000_000)
            handle.seek(start)
            if start:
                handle.readline()
            lines = handle.read().decode("utf-8", errors="replace").splitlines()[-5000:]
        count = 0
        for line in lines:
            try:
                row = json.loads(line)
                session = row.get("id") or row.get("thread_id")
                title = row.get("thread_name") or row.get("title")
                if not session or not title:
                    continue
                self.upsert_chat(session, title, source="index")
                count += 1
            except (ValueError, TypeError, AttributeError):
                continue
        return count

    def prune(self):
        with self.db() as db:
            db.execute("DELETE FROM requests WHERE status!='pending' AND updated<?", (self.clock() - 30 * 86400,))
