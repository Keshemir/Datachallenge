"""Offline manual-label templates and criterion-level comparisons. Never calls a model."""

import argparse
import json
from collections import defaultdict
from math import isfinite
from pathlib import Path

from .settings import Settings
from .storage import Store


def compare(cases: list[dict], evaluations: list[dict], split: str) -> dict:
    families: dict[str, set[str]] = defaultdict(set)
    seen = set()
    for case in cases:
        key = (case["conversation_hash"], case["checklist_hash"])
        if key in seen:
            raise ValueError("Duplicate conversation/checklist case")
        seen.add(key)
        if not case.get("family") or case.get("split") not in ("calibration", "holdout"):
            raise ValueError("Assign a scenario family and calibration/holdout split to each case")
        families[case["family"]].add(case["split"])
    if any(len(parts) > 1 for parts in families.values()):
        raise ValueError("Scenario family appears in both calibration and holdout")
    latest = {}
    for evaluation in sorted(evaluations, key=lambda e: (e["created_at"], e["id"]), reverse=True):
        latest.setdefault(
            (evaluation["conversation_hash"], evaluation["checklist_hash"]), evaluation
        )
    counts = defaultdict(lambda: {"correct": 0, "count": 0, "confusion": defaultdict(int)})
    errors, missing, unlabeled, discrepancies = [], [], [], []
    evaluated = []
    detection = {name: {"tp": 0, "fp": 0, "fn": 0} for name in ("na", "critical")}
    selected = [c for c in cases if c["split"] == split]
    for case in selected:
        if case.get("reviewed") is not True:
            unlabeled.append(case["conversation_hash"])
            continue
        actual = latest.get((case["conversation_hash"], case["checklist_hash"]))
        if not actual:
            missing.append(case["conversation_hash"])
            continue
        evaluated.append(
            {
                "evaluation_id": actual["id"],
                "conversation_hash": actual["conversation_hash"],
                "checklist_hash": actual["checklist_hash"],
                "model": actual.get("model"),
                "prompt_version": actual.get("prompt_version"),
                "created_at": actual["created_at"],
            }
        )
        decisions = case.get("decisions", {})
        results = actual["result"]["criteria"]
        if set(decisions) != {c["criterion_id"] for c in results}:
            raise ValueError("Manual labels must cover exactly the evaluation criteria")
        for c in results:
            truth = decisions[c["criterion_id"]]
            if not isinstance(truth, str) or not (
                truth in ("yes", "no", "na") or truth.startswith("score_")
            ):
                raise ValueError("Use yes/no/na/score_<number> manual labels")
            if truth.startswith("score_"):
                value = float(truth[6:])
                if not isfinite(value) or value < 0:
                    raise ValueError("Manual scale labels must be finite and nonnegative")
                truth = f"score_{value:g}"
            if c.get("kind") == "flag" and truth not in ("yes", "no"):
                raise ValueError("Critical flags require yes/no")
            if c.get("kind") == "binary" and truth not in ("yes", "no", "na"):
                raise ValueError("Binary criteria require yes/no/na")
            if c.get("kind") == "scale" and truth != "na" and not truth.startswith("score_"):
                raise ValueError("Scale criteria require score_<number>/na")
            judgment = c["judgment"]
            answer = (
                f"score_{judgment['score']:g}"
                if judgment["decision"] == "score"
                else judgment["decision"]
            )
            row = counts[c["criterion_id"]]
            row["count"] += 1
            row["correct"] += answer == truth
            row["confusion"][f"{truth} -> {answer}"] += 1
            for label, positive, applicable in (
                ("na", "na", True),
                ("critical", "yes", c.get("kind") == "flag"),
            ):
                if applicable:
                    detection[label]["tp"] += truth == positive and answer == positive
                    detection[label]["fp"] += truth != positive and answer == positive
                    detection[label]["fn"] += truth == positive and answer != positive
            if answer != truth:
                discrepancies.append(
                    {
                        "conversation_hash": case["conversation_hash"],
                        "evaluation_id": actual["id"],
                        "criterion_id": c["criterion_id"],
                        "expected": truth,
                        "actual": answer,
                    }
                )
        expected_score = case.get("total_score")
        if expected_score is not None and actual["result"]["total_score"] is not None:
            if (
                isinstance(expected_score, bool)
                or not isinstance(expected_score, (int, float))
                or not 0 <= expected_score <= 100
            ):
                raise ValueError("Manual total_score must be in 0..100 or null")
            errors.append(abs(expected_score - actual["result"]["total_score"]))
    total = sum(r["count"] for r in counts.values())
    return {
        "source": "manual local labels, not organizer Ground Truth",
        "split": split,
        "cases": len(selected),
        "unreviewed": unlabeled,
        "missing_evaluations": missing,
        "evaluations": evaluated,
        "criterion_accuracy": sum(r["correct"] for r in counts.values()) / total if total else None,
        "total_score_mae": sum(errors) / len(errors) if errors else None,
        "total_score_cases": len(errors),
        "detection": {
            name: {
                **row,
                "precision": row["tp"] / (row["tp"] + row["fp"]) if row["tp"] + row["fp"] else None,
                "recall": row["tp"] / (row["tp"] + row["fn"]) if row["tp"] + row["fn"] else None,
            }
            for name, row in detection.items()
        },
        "criteria": {
            key: {
                **row,
                "accuracy": row["correct"] / row["count"],
                "confusion": dict(row["confusion"]),
            }
            for key, row in counts.items()
        },
        "discrepancies": discrepancies,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["template", "compare"])
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=["calibration", "holdout"], default="holdout")
    args = parser.parse_args()
    store = Store(Settings.from_env().db_path)
    if args.command == "template":
        checklists = store.list_checklists()
        rubric = max(checklists, key=lambda r: r["checklist"]["version"])
        result = {
            "source": "manual local labels; fill independently of AI outputs",
            "cases": [
                {
                    "conversation_hash": c["hash"],
                    "conversation_id": c["conversation_id"],
                    "checklist_hash": rubric["hash"],
                    "family": "",
                    "split": "calibration",
                    "reviewed": False,
                    "decisions": {rule["id"]: None for rule in rubric["checklist"]["criteria"]},
                    "total_score": None,
                }
                for c in store.list_conversations()
            ],
        }
    else:
        if args.labels is None:
            parser.error("--labels is required for compare")
        result = compare(
            json.loads(args.labels.read_text(encoding="utf-8"))["cases"],
            store.list_records("evaluations"),
            args.split,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Do not overwrite hand annotations or earlier reports accidentally.
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
