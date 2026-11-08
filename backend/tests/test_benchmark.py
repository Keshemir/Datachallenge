import pytest

from cqa.benchmark import compare


def case(**extra):
    return {
        "conversation_hash": "a",
        "checklist_hash": "r",
        "family": "scenario-1",
        "split": "holdout",
        "reviewed": True,
        "decisions": {"greeting": "no", "critical": "yes"},
        "total_score": 40,
        **extra,
    }


def test_comparison_reports_disagreements_and_missing_labels():
    evaluation = {
        "id": "e1",
        "conversation_hash": "a",
        "checklist_hash": "r",
        "created_at": "2026-01-01",
        "result": {
            "total_score": 50,
            "criteria": [
                {"criterion_id": "greeting", "judgment": {"decision": "yes", "score": None}},
                {"criterion_id": "critical", "judgment": {"decision": "yes", "score": None}},
            ],
        },
    }
    result = compare(
        [case(), case(conversation_hash="b", family="other", reviewed=False)],
        [evaluation],
        "holdout",
    )
    assert result["criterion_accuracy"] == 0.5
    assert result["total_score_mae"] == 10
    assert result["unreviewed"] == ["b"]
    assert result["discrepancies"][0]["criterion_id"] == "greeting"
    assert compare([case()], [], "holdout")["criterion_accuracy"] is None


def test_scenario_leakage_and_duplicate_cases_rejected():
    with pytest.raises(ValueError, match="family"):
        compare([case(), case(conversation_hash="b", split="calibration")], [], "holdout")
    with pytest.raises(ValueError, match="Duplicate"):
        compare([case(), case()], [], "holdout")
