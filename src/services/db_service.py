from __future__ import annotations

import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_db_service_instance: Optional["DbService"] = None


def get_db_service() -> "DbService":
    if _db_service_instance is None:
        raise RuntimeError("DbService is not initialized. Call init_db_service() first.")
    return _db_service_instance


def init_db_service(db_path: str = "config/flowarchitect.db") -> "DbService":
    global _db_service_instance
    _db_service_instance = DbService(db_path)
    return _db_service_instance


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DbService:
    """
    Singleton SQLite service for FlowArchitect.
    Stores sessions, chat messages, PIM/NiFi snapshots, and LLM call logs.
    """

    def __init__(self, db_path: str = "config/flowarchitect.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._create_schema()
        logger.info("DbService initialized: %s", db_path)

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL DEFAULT 'New Session',
                mode       INTEGER NOT NULL DEFAULT 1,
                created_at TEXT    NOT NULL,
                updated_at TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role       TEXT    NOT NULL,
                content    TEXT    NOT NULL,
                created_at TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pim_snapshots (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id   INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                yaml_content TEXT    NOT NULL,
                created_at   TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS nifi_snapshots (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id   INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                json_content TEXT    NOT NULL,
                created_at   TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS llm_logs (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id       INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                provider         TEXT    NOT NULL,
                model            TEXT    NOT NULL,
                prompt_tokens    INTEGER,
                completion_tokens INTEGER,
                duration_ms      INTEGER,
                purpose          TEXT,
                cost_usd         REAL,
                created_at       TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session   ON messages(session_id);
            CREATE INDEX IF NOT EXISTS idx_pim_session        ON pim_snapshots(session_id);
            CREATE INDEX IF NOT EXISTS idx_nifi_session       ON nifi_snapshots(session_id);
            CREATE INDEX IF NOT EXISTS idx_llm_logs_session   ON llm_logs(session_id);
        """)
        self._conn.commit()
        self._ensure_llm_log_columns()

    def _ensure_llm_log_columns(self) -> None:
        cols = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(llm_logs)").fetchall()
        }
        if "cost_usd" not in cols:
            self._conn.execute("ALTER TABLE llm_logs ADD COLUMN cost_usd REAL")
            self._conn.commit()

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def create_session(self, mode: int = 1, name: str = "New Session") -> int:
        now = _now()
        cur = self._conn.execute(
            "INSERT INTO sessions (name, mode, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (name, mode, now, now),
        )
        self._conn.commit()
        session_id = cur.lastrowid
        logger.debug("Session created: id=%s name=%r", session_id, name)
        return session_id

    def update_session_name(self, session_id: int, name: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET name = ?, updated_at = ? WHERE id = ?",
            (name, _now(), session_id),
        )
        self._conn.commit()

    def update_session_mode(self, session_id: int, mode: int) -> None:
        self._conn.execute(
            "UPDATE sessions SET mode = ?, updated_at = ? WHERE id = ?",
            (mode, _now(), session_id),
        )
        self._conn.commit()

    def touch_session(self, session_id: int) -> None:
        self._conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (_now(), session_id),
        )
        self._conn.commit()

    def get_session(self, session_id: int) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_last_session(self) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def list_sessions(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: int) -> None:
        self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._conn.commit()

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def save_message(self, session_id: int, role: str, content: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, _now()),
        )
        self._conn.commit()
        self.touch_session(session_id)
        return cur.lastrowid

    def get_messages(self, session_id: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_message(self, message_id: int) -> None:
        self._conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        self._conn.commit()

    # ------------------------------------------------------------------
    # PIM snapshots
    # ------------------------------------------------------------------

    def save_pim_snapshot(self, session_id: int, yaml_content: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO pim_snapshots (session_id, yaml_content, created_at) VALUES (?, ?, ?)",
            (session_id, yaml_content, _now()),
        )
        self._conn.commit()
        self.touch_session(session_id)
        return cur.lastrowid

    def get_latest_pim(self, session_id: int) -> Optional[str]:
        row = self._conn.execute(
            "SELECT yaml_content FROM pim_snapshots WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return row["yaml_content"] if row else None

    # ------------------------------------------------------------------
    # NiFi snapshots
    # ------------------------------------------------------------------

    def save_nifi_snapshot(self, session_id: int, json_content: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO nifi_snapshots (session_id, json_content, created_at) VALUES (?, ?, ?)",
            (session_id, json_content, _now()),
        )
        self._conn.commit()
        self.touch_session(session_id)
        return cur.lastrowid

    def get_latest_nifi(self, session_id: int) -> Optional[str]:
        row = self._conn.execute(
            "SELECT json_content FROM nifi_snapshots WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return row["json_content"] if row else None

    # ------------------------------------------------------------------
    # LLM logs
    # ------------------------------------------------------------------

    def save_llm_log(
        self,
        session_id: int,
        provider: str,
        model: str,
        duration_ms: Optional[int] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        purpose: Optional[str] = None,
        cost_usd: Optional[float] = None,
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO llm_logs
               (session_id, provider, model, prompt_tokens, completion_tokens, duration_ms, purpose, cost_usd, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, provider, model, prompt_tokens, completion_tokens, duration_ms, purpose, cost_usd, _now()),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_llm_log_usage(
        self,
        log_id: int,
        prompt_tokens: Optional[int],
        completion_tokens: Optional[int],
        cost_usd: Optional[float],
    ) -> None:
        total_prompt = int(prompt_tokens or 0)
        total_completion = int(completion_tokens or 0)
        self._conn.execute(
            """UPDATE llm_logs
               SET prompt_tokens = ?, completion_tokens = ?, cost_usd = ?
               WHERE id = ?""",
            (total_prompt, total_completion, cost_usd, int(log_id)),
        )
        self._conn.commit()

    def get_llm_logs(self, session_id: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM llm_logs WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Aggregate statistics across all sessions."""
        stats: dict[str, Any] = {}

        row = self._conn.execute("SELECT COUNT(*) AS cnt FROM sessions").fetchone()
        stats["total_sessions"] = row["cnt"] if row else 0

        row = self._conn.execute("SELECT COUNT(*) AS cnt FROM messages WHERE role = 'user'").fetchone()
        stats["total_user_messages"] = row["cnt"] if row else 0

        row = self._conn.execute("SELECT COUNT(*) AS cnt FROM pim_snapshots").fetchone()
        stats["total_pim_snapshots"] = row["cnt"] if row else 0

        row = self._conn.execute("SELECT COUNT(*) AS cnt FROM nifi_snapshots").fetchone()
        stats["total_nifi_snapshots"] = row["cnt"] if row else 0

        row = self._conn.execute(
            "SELECT COUNT(*) AS cnt, AVG(duration_ms) AS avg_ms FROM llm_logs"
        ).fetchone()
        stats["total_llm_calls"] = row["cnt"] if row else 0
        avg = row["avg_ms"] if row else None
        stats["avg_duration_ms"] = round(avg) if avg is not None else None

        rows = self._conn.execute(
            "SELECT model, COUNT(*) AS cnt FROM llm_logs GROUP BY model ORDER BY cnt DESC LIMIT 10"
        ).fetchall()
        stats["top_models"] = [{"model": r["model"], "count": r["cnt"]} for r in rows]

        rows = self._conn.execute(
            "SELECT provider, COUNT(*) AS cnt FROM llm_logs GROUP BY provider ORDER BY cnt DESC"
        ).fetchall()
        stats["top_providers"] = [{"provider": r["provider"], "count": r["cnt"]} for r in rows]

        rows = self._conn.execute(
            "SELECT purpose, COUNT(*) AS cnt FROM llm_logs WHERE purpose IS NOT NULL GROUP BY purpose ORDER BY cnt DESC"
        ).fetchall()
        stats["calls_by_purpose"] = [{"purpose": r["purpose"], "count": r["cnt"]} for r in rows]

        row = self._conn.execute(
            "SELECT SUM(prompt_tokens) AS prompt, SUM(completion_tokens) AS completion, SUM(cost_usd) AS cost FROM llm_logs"
        ).fetchone()
        stats["prompt_tokens"] = row["prompt"] if row and row["prompt"] is not None else 0
        stats["completion_tokens"] = row["completion"] if row and row["completion"] is not None else 0
        stats["cost_usd"] = round(float(row["cost"]), 6) if row and row["cost"] is not None else None

        return stats

    # ------------------------------------------------------------------
    # Full session data (for restore)
    # ------------------------------------------------------------------

    def get_full_session(self, session_id: int) -> Optional[dict[str, Any]]:
        session = self.get_session(session_id)
        if not session:
            return None
        session["messages"] = self.get_messages(session_id)
        session["latest_pim"] = self.get_latest_pim(session_id)
        session["latest_nifi"] = self.get_latest_nifi(session_id)
        return session

    def close(self) -> None:
        self._conn.close()
