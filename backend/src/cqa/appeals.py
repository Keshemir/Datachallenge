"""Appeals and append-only human assessment snapshots for a shared QA workspace."""

import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import StringConstraints

from .engine import InvalidJudgments, evaluate
from .inputs import canonical_json
from .models import Judgment, Model, ModelResponse, Text
from .storage import Store

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class Submission(Model):
    evaluation_id: Name
    criterion_id: Name
    author: Name
    reason: Text


class ReviewStart(Model):
    reviewer: Name


class Resolution(ReviewStart):
    outcome: Literal["accepted", "rejected"]
    note: Text
    judgment: Judgment | None = None


def initialize_appeals(store: Store):
    with store.connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS appeals (
                id TEXT PRIMARY KEY,
                evaluation_id TEXT NOT NULL REFERENCES evaluations(id),
                criterion_id TEXT NOT NULL,
                status TEXT NOT NULL,
                body TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_open_appeal
              ON appeals(evaluation_id, criterion_id)
              WHERE status IN ('submitted', 'in_review');
            CREATE TABLE IF NOT EXISTS qa_reviews (
                id TEXT PRIMARY KEY,
                evaluation_id TEXT NOT NULL REFERENCES evaluations(id),
                appeal_id TEXT NOT NULL UNIQUE REFERENCES appeals(id),
                body TEXT NOT NULL
            );
        """)


def appeal_router(store: Store):
    router = APIRouter(prefix="/api")

    @router.get("/appeals")
    def list_appeals():
        with store.connect() as db:
            rows = db.execute("SELECT body FROM appeals ORDER BY rowid DESC").fetchall()
        return [json.loads(row["body"]) for row in rows]

    @router.get("/qa-reviews")
    def list_reviews():
        with store.connect() as db:
            rows = db.execute("SELECT body FROM qa_reviews ORDER BY rowid DESC").fetchall()
        return [json.loads(row["body"]) for row in rows]

    @router.post("/appeals", status_code=201)
    def submit(request: Submission):
        evaluation = store.evaluation(request.evaluation_id)
        if not evaluation:
            raise HTTPException(404, "Evaluation not found")
        criterion = next(
            (
                c
                for c in evaluation["result"]["criteria"]
                if c["criterion_id"] == request.criterion_id
            ),
            None,
        )
        if not criterion:
            raise HTTPException(422, "Criterion does not belong to evaluation")
        now = datetime.now(UTC).isoformat()
        record = {
            "id": str(uuid4()),
            **request.model_dump(),
            "criterion_title": criterion["title"],
            "conversation_hash": evaluation["conversation_hash"],
            "created_at": now,
            "status": "submitted",
            "events": [
                {"status": "submitted", "at": now, "actor": request.author, "note": request.reason}
            ],
        }
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM appeals WHERE evaluation_id=? AND criterion_id=? "
                "AND status IN ('submitted', 'in_review')",
                (request.evaluation_id, request.criterion_id),
            ).fetchone():
                raise HTTPException(409, "An appeal for this criterion is already open")
            db.execute(
                "INSERT INTO appeals VALUES (?, ?, ?, ?, ?)",
                (
                    record["id"],
                    request.evaluation_id,
                    request.criterion_id,
                    "submitted",
                    canonical_json(record),
                ),
            )
        return record

    def transition(key: str, request: ReviewStart | Resolution):
        with store.connect() as db:
            # Serialize concurrent resolutions so each snapshot incorporates all earlier decisions.
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM appeals WHERE id=?", (key,)).fetchone()
            if not row:
                raise HTTPException(404, "Appeal not found")
            record = json.loads(row["body"])
            resolving = isinstance(request, Resolution)
            expected = "in_review" if resolving else "submitted"
            if record["status"] != expected:
                raise HTTPException(409, "Appeal status has changed; refresh")
            now = datetime.now(UTC).isoformat()
            status = request.outcome if resolving else "in_review"
            note = request.note if resolving else "Апелляция принята в работу."
            event = {"status": status, "at": now, "actor": request.reviewer, "note": note}
            if resolving and request.outcome == "accepted":
                if (
                    request.judgment is None
                    or request.judgment.criterion_id != record["criterion_id"]
                ):
                    raise HTTPException(
                        422, "Accepted appeal requires a judgment for its criterion"
                    )
                original = json.loads(
                    db.execute(
                        "SELECT body FROM evaluations WHERE id=?", (record["evaluation_id"],)
                    ).fetchone()["body"]
                )
                previous = db.execute(
                    "SELECT body FROM qa_reviews WHERE evaluation_id=? ORDER BY rowid DESC LIMIT 1",
                    (record["evaluation_id"],),
                ).fetchone()
                base = json.loads(previous["body"]) if previous else original
                judgments = [
                    request.judgment
                    if c["criterion_id"] == record["criterion_id"]
                    else Judgment.model_validate(c["judgment"])
                    for c in base["result"]["criteria"]
                ]
                try:
                    result = evaluate(
                        store.conversation(original["conversation_hash"]),
                        store.checklist(original["checklist_hash"]),
                        ModelResponse(judgments=judgments),
                    )
                except InvalidJudgments as exc:
                    raise HTTPException(422, "Invalid evidence or criterion decision") from exc
                snapshot = {
                    "id": str(uuid4()),
                    "evaluation_id": record["evaluation_id"],
                    "appeal_id": key,
                    "created_at": now,
                    "reviewer": request.reviewer,
                    "previous_review_id": base["id"] if previous else None,
                    "result": result.model_dump(mode="json"),
                }
                db.execute(
                    "INSERT INTO qa_reviews VALUES (?, ?, ?, ?)",
                    (
                        snapshot["id"],
                        record["evaluation_id"],
                        key,
                        canonical_json(snapshot),
                    ),
                )
                event["review_id"] = snapshot["id"]
            elif resolving and request.judgment is not None:
                raise HTTPException(422, "Rejected appeal must not change the judgment")
            record["status"] = status
            record["events"].append(event)
            db.execute(
                "UPDATE appeals SET status=?, body=? WHERE id=?",
                (status, canonical_json(record), key),
            )
        return record

    @router.post("/appeals/{key}/start")
    def start(key: str, request: ReviewStart):
        return transition(key, request)

    @router.post("/appeals/{key}/resolve")
    def resolve(key: str, request: Resolution):
        return transition(key, request)

    return router
