"""Conversation sessions. Verified identity lives here, out of the model's reach."""

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from emporio.memory.redact import redact


@dataclass
class Session:
    session_id: str
    verified_customer_id: int | None = None
    verified_at: datetime | None = None
    failed_verifications: int = 0
    evidence: str = ""


def create_session(connection: sqlite3.Connection, now: datetime) -> Session:
    session_id = secrets.token_urlsafe(32)
    connection.execute(
        "INSERT INTO sessions (session_id, created_at, last_seen_at) VALUES (?, ?, ?)",
        (session_id, now.isoformat(), now.isoformat()),
    )
    return Session(session_id)


def load_session(
    connection: sqlite3.Connection, session_id: str, now: datetime, ttl_minutes: int
) -> Session | None:
    row = connection.execute(
        "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if row is None:
        return None
    session = Session(
        session_id=row["session_id"],
        verified_customer_id=row["verified_customer_id"],
        verified_at=datetime.fromisoformat(row["verified_at"]) if row["verified_at"] else None,
        failed_verifications=row["failed_verifications"],
        evidence=row["evidence"],
    )
    last_seen = datetime.fromisoformat(row["last_seen_at"])
    if session.verified_customer_id is not None and now - last_seen > timedelta(
        minutes=ttl_minutes
    ):
        session.verified_customer_id = None
        session.verified_at = None
    return session


def save_session(connection: sqlite3.Connection, session: Session, now: datetime) -> None:
    connection.execute(
        """
        UPDATE sessions
        SET last_seen_at = ?, verified_customer_id = ?, verified_at = ?,
            failed_verifications = ?, evidence = ?
        WHERE session_id = ?
        """,
        (
            now.isoformat(),
            session.verified_customer_id,
            session.verified_at.isoformat() if session.verified_at else None,
            session.failed_verifications,
            session.evidence,
            session.session_id,
        ),
    )


def history(connection: sqlite3.Connection, session_id: str, turns: int) -> list[dict[str, str]]:
    """The last `turns` exchanges, oldest first."""
    rows = connection.execute(
        """
        SELECT role, content FROM turns
        WHERE session_id = ? AND turn > (SELECT COALESCE(MAX(turn), 0) - ? FROM turns
                                         WHERE session_id = ?)
        ORDER BY turn, role DESC
        """,
        (session_id, turns, session_id),
    ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def next_turn(connection: sqlite3.Connection, session_id: str) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(turn), 0) + 1 AS turn FROM turns WHERE session_id = ?", (session_id,)
    ).fetchone()
    return int(row["turn"])


def append_turn(
    connection: sqlite3.Connection,
    session_id: str,
    turn: int,
    user_text: str,
    reply: str,
    now: datetime,
) -> None:
    connection.executemany(
        "INSERT INTO turns VALUES (?, ?, ?, ?, ?)",
        [
            (session_id, turn, "user", redact(user_text), now.isoformat()),
            (session_id, turn, "assistant", reply, now.isoformat()),
        ],
    )
