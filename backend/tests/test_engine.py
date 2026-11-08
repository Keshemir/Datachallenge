import pytest
from pydantic import ValidationError

from cqa.engine import InvalidJudgments, evaluate
from cqa.inputs import fingerprint, normalize_conversation
from cqa.models import Checklist, ConversationInput, Criterion, ModelResponse


def test_full_score_and_critical_flag_are_independent(conversation, checklist, judgments):
    result = evaluate(conversation, checklist, judgments)
    assert result.total_score == 100
    assert result.flagged_criteria == ["critical"]
    assert result.criteria[-1].earned_weight is None
    assert result.criteria[-1].contribution is None


def test_scale_7_of_10_gives_10_5_of_15(conversation, checklist, judgments):
    judgments.judgments[5].score = 7
    result = evaluate(conversation, checklist, judgments)
    assert result.total_score == 95.5
    assert result.criteria[5].earned_weight == 10.5


def test_na_redistributes_weights_and_rounds_final_only(conversation, checklist, judgments):
    for index in (1, 2):
        judgments.judgments[index].decision = "na"
        judgments.judgments[index].na_reason = "Test applicability condition"
    judgments.judgments[0].decision = "no"
    result = evaluate(conversation, checklist, judgments)
    assert result.applicable_weight == 65
    assert result.total_score == 84.62
    assert result.criteria[1].effective_weight == 0
    assert result.criteria[1].contribution is None
    assert sum(r.effective_weight for r in result.criteria) == pytest.approx(100)
    assert sum(r.contribution or 0 for r in result.criteria) == pytest.approx(100 * 55 / 65)


def test_no_scored_criteria_has_no_total(conversation, checklist, judgments):
    only_flag = checklist.model_copy(update={"criteria": [checklist.criteria[-1]]})
    response = ModelResponse(judgments=[judgments.judgments[-1]])
    assert evaluate(conversation, only_flag, response).total_score is None


def test_all_scored_criteria_na_has_no_total(conversation, checklist, judgments):
    custom = checklist.model_copy(update={"criteria": [checklist.criteria[1]]})
    judgment = judgments.judgments[1]
    judgment.decision = "na"
    judgment.na_reason = "Known details sufficient"
    result = evaluate(conversation, custom, ModelResponse(judgments=[judgment]))
    assert result.total_score is None
    assert result.sections[0].score is None


@pytest.mark.parametrize("bad_score", [1, 5, 8, 11])
def test_disallowed_management_step_rejected(conversation, checklist, judgments, bad_score):
    judgments.judgments[5].score = bad_score
    with pytest.raises(InvalidJudgments, match="allowed scale"):
        evaluate(conversation, checklist, judgments)


@pytest.mark.parametrize("index", [0, 4, 5, 7])
def test_na_forbidden_where_not_configured(conversation, checklist, judgments, index):
    judgment = judgments.judgments[index]
    judgment.decision, judgment.score, judgment.na_reason = "na", None, "No evidence"
    with pytest.raises(InvalidJudgments, match="N/A"):
        evaluate(conversation, checklist, judgments)


def test_bot_greeting_cannot_be_operator_evidence(conversation, checklist, judgments):
    judgments.judgments[0].evidence_message_ids = ["m0002"]
    with pytest.raises(InvalidJudgments, match="first operator"):
        evaluate(conversation, checklist, judgments)


def test_later_operator_greeting_cannot_replace_first(conversation, checklist, judgments):
    judgments.judgments[0].evidence_message_ids = ["m0005"]
    with pytest.raises(InvalidJudgments, match="first operator"):
        evaluate(conversation, checklist, judgments)


def test_system_evidence_allowed_for_identification(conversation, checklist, judgments):
    judgments.judgments[2].evidence_message_ids = ["m0004"]
    result = evaluate(conversation, checklist, judgments)
    assert result.criteria[2].evidence[0].text == conversation.transcript[3].text


def test_unknown_evidence_is_rejected(conversation, checklist, judgments):
    judgments.judgments[2].evidence_message_ids = ["invented"]
    with pytest.raises(InvalidJudgments, match="unknown message"):
        evaluate(conversation, checklist, judgments)


def test_omission_uses_checked_range_without_fake_quote(conversation, checklist, judgments):
    judgment = judgments.judgments[0]
    judgment.decision, judgment.evidence_message_ids = "no", []
    result = evaluate(conversation, checklist, judgments)
    assert result.total_score == 90
    assert result.criteria[0].evidence == []


def test_positive_judgment_requires_message(conversation, checklist, judgments):
    judgments.judgments[0].evidence_message_ids = []
    with pytest.raises(InvalidJudgments, match="supporting message"):
        evaluate(conversation, checklist, judgments)


@pytest.mark.parametrize("start,end", [("m0005", "m0001"), ("absent", "m0005")])
def test_invalid_range_rejected(conversation, checklist, judgments, start, end):
    judgments.judgments[0].checked_range.start_message_id = start
    judgments.judgments[0].checked_range.end_message_id = end
    with pytest.raises(InvalidJudgments, match="range"):
        evaluate(conversation, checklist, judgments)


@pytest.mark.parametrize("change", ["missing", "duplicate", "extra"])
def test_exact_criterion_coverage(conversation, checklist, judgments, change):
    if change == "missing":
        judgments.judgments.pop()
    elif change == "duplicate":
        judgments.judgments.append(judgments.judgments[0])
    else:
        judgments.judgments.append(
            judgments.judgments[0].model_copy(update={"criterion_id": "new"})
        )
    with pytest.raises(InvalidJudgments):
        evaluate(conversation, checklist, judgments)


def test_custom_criterion_and_non_100_weight_sum(conversation, judgments):
    criterion = Criterion(
        id="custom-rule",
        title="Custom",
        section="Custom",
        kind="binary",
        weight=3,
        instructions="Custom rule from UI",
    )
    checklist = Checklist(
        id="custom", version=2, title="Custom", instructions="Custom", criteria=[criterion]
    )
    response = ModelResponse(
        judgments=[judgments.judgments[0].model_copy(update={"criterion_id": criterion.id})]
    )
    result = evaluate(conversation, checklist, response)
    assert result.total_score == 100
    assert result.criteria[0].effective_weight == 100


def test_changed_content_changes_hash_with_same_source_id(conversation):
    changed = conversation.model_copy(deep=True)
    changed.transcript[0].text += " Новая информация."
    assert fingerprint(changed) != fingerprint(conversation)


def test_original_text_order_timestamps_preserved():
    raw = {
        "conversation_id": "voice",
        "channel": "voice call",
        "language": "RU",
        "transcript": [
            {
                "timestamp": "2026-11-03T12:50:05.4638614+00:00",
                "speaker": "operator",
                "text": "  [Имя скрыто] Здравствуйте!  ",
            }
        ],
    }
    source = ConversationInput.model_validate(raw)
    normalized = normalize_conversation(source)
    assert normalized.transcript[0].model_dump(exclude={"message_id"}) == raw["transcript"][0]
    assert normalize_conversation(source) == normalized


@pytest.mark.parametrize("weight", [-1, float("nan"), float("inf"), True])
def test_bad_weights_rejected(weight):
    with pytest.raises(ValidationError):
        Criterion(
            id="bad", title="Bad", section="Bad", kind="binary", weight=weight, instructions="Bad"
        )


def test_flag_cannot_change_total_by_configuration():
    with pytest.raises(ValidationError):
        Criterion(
            id="flag", title="Flag", section="Flag", kind="flag", weight=5, instructions="Flag"
        )
