from pathlib import Path
import sqlite3
from .utils import parse_stored_timestamp

DB_PATH = Path("whatsapp_chat.db")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sender_mappings (
                raw_sender TEXT PRIMARY KEY,
                matched_name TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                raw_sender TEXT NOT NULL,
                matched_name TEXT NOT NULL,
                message TEXT NOT NULL,
                is_selected INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(messages)").fetchall()
        }
        if "is_selected" not in cols:
            conn.execute(
                "ALTER TABLE messages ADD COLUMN is_selected INTEGER NOT NULL DEFAULT 1"
            )

def get_latest_message_datetime(conn: sqlite3.Connection):
    rows = conn.execute("SELECT timestamp FROM messages").fetchall()
    latest_dt = None
    for r in rows:
        dt = parse_stored_timestamp(r["timestamp"])
        if dt is not None and (latest_dt is None or dt > latest_dt):
            latest_dt = dt
    return latest_dt


def resolve_and_store_messages(parsed_messages: list[dict]) -> int:
    inserted = 0
    with get_db() as conn:
        latest_dt = get_latest_message_datetime(conn)

        for item in parsed_messages:
            msg_dt = parse_stored_timestamp(item["timestamp"])
            if latest_dt is not None and msg_dt is not None and msg_dt <= latest_dt:
                continue

            raw_sender = item["sender"]
            conn.execute(
                """
                INSERT OR IGNORE INTO sender_mappings (raw_sender, matched_name)
                VALUES (?, ?)
                """,
                (raw_sender, raw_sender),
            )
            row = conn.execute(
                "SELECT matched_name FROM sender_mappings WHERE raw_sender = ?",
                (raw_sender,),
            ).fetchone()
            matched_name = row["matched_name"]

            conn.execute(
                """
                INSERT INTO messages (timestamp, raw_sender, matched_name, message)
                VALUES (?, ?, ?, ?)
                """,
                (item["timestamp"], raw_sender, matched_name, item["message"]),
            )
            inserted += 1
    return inserted

def get_all_mappings() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT raw_sender, matched_name FROM sender_mappings ORDER BY raw_sender"
        ).fetchall()
    return [dict(r) for r in rows]


def update_sender_mappings(raw_senders: list[str], matched_names: list[str]) -> None:
    with get_db() as conn:
        for raw_s, matched_n in zip(raw_senders, matched_names):
            cleaned_match = matched_n.strip() or raw_s
            conn.execute(
                "UPDATE sender_mappings SET matched_name = ? WHERE raw_sender = ?",
                (cleaned_match, raw_s),
            )
            conn.execute(
                "UPDATE messages SET matched_name = ? WHERE raw_sender = ?",
                (cleaned_match, raw_s),
            )


def get_recent_messages(limit: int = 100) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT timestamp, matched_name, message FROM messages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "timestamp": r["timestamp"],
            "sender": r["matched_name"],
            "message": r["message"],
        }
        for r in reversed(rows)
    ]


def get_distinct_senders() -> list[str]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT matched_name FROM messages ORDER BY matched_name"
        ).fetchall()
    return [r["matched_name"] for r in rows]


def get_messages_for_filter(sender: str | None = None) -> list[dict]:
    with get_db() as conn:
        if sender:
            rows = conn.execute(
                """
                SELECT matched_name, timestamp, message
                FROM messages
                WHERE matched_name = ?
                ORDER BY id ASC
                """,
                (sender,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT matched_name, timestamp, message
                FROM messages
                ORDER BY id ASC
                """
            ).fetchall()
    return [dict(r) for r in rows]

def get_all_messages_ordered() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, timestamp, raw_sender, matched_name, message, is_selected
            FROM messages
            ORDER BY id ASC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def delete_messages_by_ids(message_ids: list[int]) -> int:
    if not message_ids:
        return 0
    placeholders = ",".join("?" for _ in message_ids)
    with get_db() as conn:
        cur = conn.execute(
            f"DELETE FROM messages WHERE id IN ({placeholders})",
            message_ids,
        )
        return cur.rowcount

def update_day_selection(day_msg_ids: list[int], selected_ids: list[int]) -> None:
    if not day_msg_ids:
        return
    selected_set = set(selected_ids)
    with get_db() as conn:
        for msg_id in day_msg_ids:
            flag = 1 if msg_id in selected_set else 0
            conn.execute(
                "UPDATE messages SET is_selected = ? WHERE id = ?",
                (flag, msg_id),
            )

def get_distinct_senders() -> list[str]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT matched_name
            FROM messages
            WHERE is_selected = 1
            ORDER BY matched_name
            """
        ).fetchall()
    return [r["matched_name"] for r in rows]

def get_messages_for_filter(sender: str | None = None) -> list[dict]:
    with get_db() as conn:
        if sender:
            rows = conn.execute(
                """
                SELECT matched_name, timestamp, message
                FROM messages
                WHERE is_selected = 1 AND matched_name = ?
                ORDER BY id ASC
                """,
                (sender,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT matched_name, timestamp, message
                FROM messages
                WHERE is_selected = 1
                ORDER BY id ASC
                """
            ).fetchall()
    return [dict(r) for r in rows]