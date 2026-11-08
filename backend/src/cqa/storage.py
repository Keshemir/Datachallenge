import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .inputs import canonical_json, fingerprint
from .models import Checklist, Conversation


class ChecklistConflict(ValueError):
    pass


class Store:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    hash TEXT PRIMARY KEY, source_id TEXT NOT NULL, body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS checklists (
                    hash TEXT PRIMARY KEY, checklist_id TEXT NOT NULL,
                    version INTEGER NOT NULL, body TEXT NOT NULL,
                    UNIQUE(checklist_id, version)
                );
                CREATE TABLE IF NOT EXISTS evaluations (
                    id TEXT PRIMARY KEY,
                    conversation_hash TEXT NOT NULL REFERENCES conversations(hash),
                    checklist_hash TEXT NOT NULL REFERENCES checklists(hash),
                    body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transcriptions (
                    id TEXT PRIMARY KEY,
                    source_conversation_hash TEXT REFERENCES conversations(hash),
                    body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decision_checks (
                    id TEXT PRIMARY KEY,
                    evaluation_id TEXT NOT NULL REFERENCES evaluations(id),
                    body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transcript_derivations (
                    conversation_hash TEXT PRIMARY KEY REFERENCES conversations(hash),
                    transcription_id TEXT NOT NULL REFERENCES transcriptions(id),
                    assignment TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS external_calls (
                    id TEXT PRIMARY KEY, body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS submission_datasets (
                    hash TEXT PRIMARY KEY, body TEXT NOT NULL
                );
            """)

    def save_conversations(self, conversations: list[Conversation]) -> list[str]:
        keys = [fingerprint(c) for c in conversations]
        with self.connect() as db:
            db.executemany(
                "INSERT OR IGNORE INTO conversations VALUES (?, ?, ?)",
                [
                    (key, c.conversation_id, canonical_json(c))
                    for key, c in zip(keys, conversations, strict=True)
                ],
            )
        return keys

    def save_dataset(self, group_id: str, conversations: list[Conversation]) -> str:
        """Pin organizer membership and source hashes, independently of later derived chats."""
        self.save_conversations(conversations)
        manifest = {
            "group_id": group_id,
            "members": [
                {"conversation_id": c.conversation_id, "hash": fingerprint(c), "channel": c.channel}
                for c in conversations
            ],
        }
        key = fingerprint(manifest)
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO submission_datasets VALUES (?, ?)",
                (key, canonical_json(manifest)),
            )
        return key

    def submission_datasets(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT hash, body FROM submission_datasets ORDER BY rowid DESC"
            ).fetchall()
        return [{"hash": r["hash"], **json.loads(r["body"])} for r in rows]

    def conversation(self, key: str) -> Conversation | None:
        with self.connect() as db:
            row = db.execute("SELECT body FROM conversations WHERE hash = ?", (key,)).fetchone()
        return Conversation.model_validate_json(row["body"]) if row else None

    def list_conversations(self, query: str = "") -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT c.hash, c.body, d.transcription_id, t.rowid AS transcription_number FROM conversations c "
                "LEFT JOIN transcript_derivations d ON d.conversation_hash=c.hash "
                "LEFT JOIN transcriptions t ON t.id=d.transcription_id "
                "ORDER BY c.source_id, c.hash"
            ).fetchall()
        summaries = []
        for row in rows:
            body = json.loads(row["body"])
            display_name = (
                f"Расшифровка №{row['transcription_number']}"
                if row["transcription_id"]
                else body["conversation_id"]
            )
            if query.strip():
                needle = query.strip().casefold()
                haystack = " ".join(
                    [
                        display_name,
                        body["conversation_id"],
                        *[m["text"] for m in body["transcript"]],
                    ]
                )
                if needle not in haystack.casefold():
                    continue
            summaries.append(
                {
                    "hash": row["hash"],
                    "conversation_id": body["conversation_id"],
                    "display_name": display_name,
                    "language": body["language"],
                    "channel": body["channel"],
                    "message_count": len(body["transcript"]),
                    "has_audio": bool(body.get("audio_url")),
                    "transcription_id": row["transcription_id"],
                    "preview": next(
                        (m["text"][:160] for m in body["transcript"] if m["speaker"] == "client"),
                        body["transcript"][0]["text"][:160],
                    ),
                }
            )
        return summaries

    def save_checklist(self, checklist: Checklist) -> str:
        key = fingerprint(checklist)
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO checklists VALUES (?, ?, ?, ?)",
                (key, checklist.id, checklist.version, canonical_json(checklist)),
            )
            row = db.execute(
                "SELECT hash FROM checklists WHERE checklist_id=? AND version=?",
                (checklist.id, checklist.version),
            ).fetchone()
            if row and row["hash"] != key:
                raise ChecklistConflict("This version is immutable; increment checklist.version")
        return key

    def checklist(self, key: str) -> Checklist | None:
        with self.connect() as db:
            row = db.execute("SELECT body FROM checklists WHERE hash=?", (key,)).fetchone()
        return Checklist.model_validate_json(row["body"]) if row else None

    def list_checklists(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT hash, body FROM checklists ORDER BY checklist_id, version"
            ).fetchall()
        return [{"hash": row["hash"], "checklist": json.loads(row["body"])} for row in rows]

    def save_evaluation(self, record: dict):
        with self.connect() as db:
            db.execute(
                "INSERT INTO evaluations VALUES (?, ?, ?, ?)",
                (
                    record["id"],
                    record["conversation_hash"],
                    record["checklist_hash"],
                    canonical_json(record),
                ),
            )

    def evaluation(self, key: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT body FROM evaluations WHERE id=?", (key,)).fetchone()
        return json.loads(row["body"]) if row else None

    def save_transcription(self, record: dict, audio_content: bytes):
        audio_dir = self.path.parent / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        target = audio_dir / f"{record['audio_sha256']}.{record['audio_format']}"
        if not target.exists():
            target.write_bytes(audio_content)
        with self.connect() as db:
            db.execute(
                "INSERT INTO transcriptions VALUES (?, ?, ?)",
                (record["id"], record["source_conversation_hash"], canonical_json(record)),
            )

    def transcription(self, key: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT body FROM transcriptions WHERE id=?", (key,)).fetchone()
        return json.loads(row["body"]) if row else None

    def save_decision_check(self, record: dict):
        with self.connect() as db:
            db.execute(
                "INSERT INTO decision_checks VALUES (?, ?, ?)",
                (record["id"], record["evaluation_id"], canonical_json(record)),
            )

    def list_records(self, kind: str) -> list[dict]:
        if kind not in ("transcriptions", "decision_checks", "evaluations", "external_calls"):
            raise ValueError("Unsupported record type")
        with self.connect() as db:
            rows = db.execute(f"SELECT body FROM {kind} ORDER BY rowid DESC").fetchall()
        return [json.loads(row["body"]) for row in rows]

    def save_derivation(self, conversation: Conversation, transcription_id: str, assignment: dict):
        key = fingerprint(conversation)
        # Creation of the transcript and its provenance is atomic.
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO conversations VALUES (?, ?, ?)",
                (key, conversation.conversation_id, canonical_json(conversation)),
            )
            db.execute(
                "INSERT OR IGNORE INTO transcript_derivations VALUES (?, ?, ?)",
                (key, transcription_id, canonical_json(assignment)),
            )
        return key

    def transcription_derivation(self, transcription_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT conversation_hash, assignment FROM transcript_derivations WHERE transcription_id=? ORDER BY rowid DESC LIMIT 1",
                (transcription_id,),
            ).fetchone()
        return (
            {"hash": row["conversation_hash"], "assignment": json.loads(row["assignment"])}
            if row
            else None
        )

    def save_call(self, record: dict):
        with self.connect() as db:
            db.execute(
                "INSERT INTO external_calls VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                (record["id"], canonical_json(record)),
            )
