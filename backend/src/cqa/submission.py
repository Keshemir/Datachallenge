"""Organizer Results JSON 1.0: pure export of saved AI evaluations, no inference."""

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import Field, ValidationError

from .engine import InvalidJudgments, evaluate
from .inputs import fingerprint, normalize_conversation
from .models import DatasetEnvelope, Judgment, Model, ModelResponse
from .settings import Settings
from .storage import Store

ALIASES = {"needs": "discovery", "management": "dialogue", "closing": "closure"}
# Public specification, not the mutable checklist editor state.
SPEC = {
    "contact": ("binary", 10, False, ()),
    "discovery": ("binary", 15, True, ()),
    "identification": ("binary", 20, True, ()),
    "consultation": ("scale", 20, True, (0, 5, 10, 15, 20)),
    "empathy": ("binary", 15, False, ()),
    "dialogue": ("scale", 15, False, (0, 4, 7, 10)),
    "closure": ("binary", 5, True, ()),
    "critical": ("flag", 0, False, ()),
}


class SubmissionRequest(Model):
    dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    checklist_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    split: Literal["dev", "prod"]
    team_name: str = Field(min_length=1, max_length=150, pattern=r"\S")


def official_id(identifier: str) -> str:
    return ALIASES.get(identifier, identifier)


def checklist_problem(checklist) -> str | None:
    ids = [official_id(c.id) for c in checklist.criteria]
    if len(ids) != len(set(ids)) or set(ids) != set(SPEC):
        return "Для JSON 1.0 нужны ровно восемь официальных критериев без повторов."
    for criterion in checklist.criteria:
        expected = SPEC[official_id(criterion.id)]
        actual = (
            criterion.kind,
            criterion.weight,
            criterion.allow_na,
            tuple(sorted(s.value for s in criterion.scale)),
        )
        if actual != expected:
            return f"Критерий «{criterion.title}»: вес, шкала или допустимость N/A отличаются от JSON 1.0."
    return None


def convert_evaluation(conversation, checklist, record: dict) -> dict:
    if record["conversation_hash"] != fingerprint(conversation) or record[
        "checklist_hash"
    ] != fingerprint(checklist):
        raise ValueError("Оценка относится к другому транскрипту или чек-листу.")
    judgments = [Judgment.model_validate(c["judgment"]) for c in record["result"]["criteria"]]
    # Revalidate evidence, scales and original message order; recompute with the shared Decimal engine.
    recalculated = evaluate(conversation, checklist, ModelResponse(judgments=judgments))
    if recalculated.total_score != record["result"]["total_score"] or set(
        recalculated.flagged_criteria
    ) != set(record["result"]["flagged_criteria"]):
        raise ValueError("Сохранённый итог или флаг не совпадает с решениями по критериям.")
    if recalculated.total_score is None:
        raise ValueError("Не удалось получить числовой итог.")
    positions = {m.message_id: i for i, m in enumerate(conversation.transcript, 1)}
    criteria = {}
    for result in recalculated.criteria:
        judgment = result.judgment
        value = {"yes": True, "no": False, "na": None}.get(judgment.decision)
        if judgment.decision == "score":
            value = int(judgment.score)
        evidence = {positions[mid] for mid in judgment.evidence_message_ids}
        # An absent action is supported by its checked span, not an invented quote.
        if judgment.checked_range:
            evidence.update(
                range(
                    positions[judgment.checked_range.start_message_id],
                    positions[judgment.checked_range.end_message_id] + 1,
                )
            )
        rationale = judgment.explanation.strip()
        if judgment.na_reason and judgment.na_reason.strip() not in rationale:
            rationale += " " + judgment.na_reason.strip()
        key = official_id(result.criterion_id)
        criteria[key] = {
            "criterion_id": key,
            "value": value,
            "rationale": rationale,
            "evidence_turns": sorted(evidence),
        }
    return {
        "conversation_id": conversation.conversation_id,
        "status": "ok",
        "criteria": [criteria[key] for key in SPEC],
        "score": {
            "final_score": recalculated.total_score,
            "critical_flag": criteria["critical"]["value"],
        },
    }


def build_submission(store: Store, request: SubmissionRequest) -> dict:
    manifest = next(
        (d for d in store.submission_datasets() if d["hash"] == request.dataset_hash), None
    )
    checklist = store.checklist(request.checklist_hash)
    if manifest is None or checklist is None:
        raise ValueError("Исходный набор или версия чек-листа не найдены.")
    issues = []
    members = manifest["members"]
    counts = Counter(m["channel"] for m in members)
    expected = {"agent chat": 60, "voice call": 5} if request.split == "dev" else {"agent chat": 10}
    if counts != expected:
        issues.append(
            "Нужны 60 чатов и 5 звонков для DEV."
            if request.split == "dev"
            else "Нужны ровно 10 чатов для PROD."
        )
    ids = [m["conversation_id"] for m in members]
    if len(ids) != len(set(ids)):
        issues.append("В исходном наборе повторяются conversation_id.")
    group = manifest["group_id"].strip().lower()
    if group in ("dev", "prod") and group != request.split:
        issues.append("Выбранный тип сдачи не совпадает с группой исходного набора.")
    problem = checklist_problem(checklist)
    if problem:
        issues.append(problem)
    # Store order is insertion order (latest first), independent of clock drift.
    latest = {}
    for record in store.list_records("evaluations"):
        if record["checklist_hash"] == request.checklist_hash:
            latest.setdefault(record["conversation_hash"], record)
    models, results, errors = set(), [], []
    for member in members:
        record = latest.get(member["hash"])
        reason = "Нет сохранённой AI-оценки исходного транскрипта по выбранной версии чек-листа."
        if record and isinstance(record.get("model"), str) and record["model"].strip():
            models.add(record["model"].strip())
            try:
                if problem:
                    raise ValueError(problem)
                conversation = store.conversation(member["hash"])
                if (
                    conversation is None
                    or conversation.conversation_id != member["conversation_id"]
                ):
                    raise ValueError("Исходный транскрипт отсутствует или его ID изменён.")
                results.append(convert_evaluation(conversation, checklist, record))
                continue
            except (ValueError, KeyError, TypeError, ValidationError, InvalidJudgments):
                reason = "Сохранённая оценка не прошла проверку соответствия исходному транскрипту и формату JSON 1.0."
        elif record:
            reason = "В сохранённой оценке не указана фактически использованная модель."
        results.append(
            {
                "conversation_id": member["conversation_id"],
                "status": "error",
                "criteria": [],
                "score": None,
                "error": reason,
            }
        )
        errors.append(
            {
                "conversation_id": member["conversation_id"],
                "conversation_hash": member["hash"],
                "reason": reason,
            }
        )
    if not models:
        issues.append(
            "Нет сохранённых сведений о фактически использованной модели. Сначала оцените исходные диалоги."
        )
    payload = {
        "schema_version": "1.0",
        "team_name": request.team_name.strip(),
        # All current application evaluators use external APIs; never infer this from model branding.
        "model": {"mode": "external_api", "name": ", ".join(sorted(models))},
        "results": results,
    }
    return {
        "ready": not issues,
        "issues": issues,
        "errors": errors,
        "summary": {"total": len(results), "ok": len(results) - len(errors), "error": len(errors)},
        "target_path": f"results/{request.split}/results.json",
        "payload": payload if not issues else None,
    }


def submission_router(store: Store):
    router = APIRouter(prefix="/api/submissions")

    @router.get("/datasets")
    def datasets():
        return [
            {
                "hash": d["hash"],
                "group_id": d["group_id"],
                "count": len(d["members"]),
                "chats": sum(m["channel"] == "agent chat" for m in d["members"]),
                "calls": sum(m["channel"] == "voice call" for m in d["members"]),
            }
            for d in store.submission_datasets()
        ]

    @router.post("/preview")
    def preview(request: SubmissionRequest):
        try:
            return build_submission(store, request)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    return router


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="Original organizer API JSON")
    parser.add_argument("--split", choices=["dev", "prod"], required=True)
    parser.add_argument("--team-name", required=True)
    parser.add_argument("--checklist-hash", required=True)
    parser.add_argument(
        "--check", action="store_true", help="Validate without writing results.json"
    )
    parser.add_argument("--include-errors", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    store = Store(Settings.from_env().db_path)
    store.initialize()
    envelope = DatasetEnvelope.model_validate_json(args.dataset.read_text(encoding="utf-8-sig"))
    key = store.save_dataset(
        envelope.data.dataset_group_id, [normalize_conversation(c) for c in envelope.data.records]
    )
    report = build_submission(
        store,
        SubmissionRequest(
            dataset_hash=key,
            checklist_hash=args.checklist_hash,
            split=args.split,
            team_name=args.team_name,
        ),
    )
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "payload"}, ensure_ascii=False, indent=2
        )
    )
    if not report["ready"]:
        raise SystemExit(2)
    if args.check:
        return
    if report["errors"] and not args.include_errors:
        parser.error("Review error records; use --include-errors to export them explicitly")
    target = Path(report["target_path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w" if args.overwrite else "x", encoding="utf-8", newline="\n") as stream:
        json.dump(report["payload"], stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(f"Saved {target}; no commit or push performed.")


if __name__ == "__main__":
    main()
