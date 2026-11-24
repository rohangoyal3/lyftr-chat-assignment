import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .schemas import Metadata


class Storage:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=5)) as connection, connection:
            connection.row_factory = sqlite3.Row
            yield connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    system_prompt TEXT
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS messages_by_session ON messages(session_id, id);
            """)

    def check(self) -> None:
        with self.connect() as connection:
            connection.execute("SELECT 1 FROM sessions LIMIT 1").fetchone()

    def load(self, session_id: str) -> tuple[bool, str | None, list[dict]]:
        with self.connect() as connection:
            # A read transaction keeps the prompt and its messages on the same snapshot.
            connection.execute("BEGIN")
            session = connection.execute(
                "SELECT system_prompt FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if session is None:
                return False, None, []
            rows = connection.execute(
                "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()

        messages = []
        for row in rows:
            message = {"role": row["role"], "content": row["content"]}
            if row["metadata"] is not None:
                message["metadata"] = json.loads(row["metadata"])
            messages.append(message)
        return True, session["system_prompt"], messages

    def save_turn(
        self, session_id: str, system_prompt: str | None, user_text: str, reply: str, metadata: Metadata
    ) -> None:
        user_time = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        assistant_time = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO sessions(id, system_prompt) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET system_prompt = excluded.system_prompt",
                (session_id, system_prompt),
            )
            connection.executemany(
                "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
                [
                    (session_id, "user", user_text, None, user_time),
                    (session_id, "assistant", reply, metadata.model_dump_json(), assistant_time),
                ],
            )
