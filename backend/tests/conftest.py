import pytest

from cqa.inputs import default_checklist, normalize_conversation
from cqa.models import CheckedRange, ConversationInput, Judgment, ModelResponse


@pytest.fixture
def conversation():
    return normalize_conversation(
        ConversationInput.model_validate(
            {
                "conversation_id": "test-only",
                "channel": "agent chat",
                "language": "RU",
                "transcript": [
                    {"timestamp": "00:00", "speaker": "client", "text": "Где отчёт?"},
                    {"timestamp": "00:01", "speaker": "bot", "text": "Здравствуйте, я бот."},
                    {
                        "timestamp": "00:02",
                        "speaker": "operator",
                        "text": "Здравствуйте, я Анна. Откройте отчёты.",
                    },
                    {
                        "timestamp": "00:03",
                        "speaker": "system",
                        "text": "Личность клиента подтверждена.",
                    },
                    {
                        "timestamp": "00:04",
                        "speaker": "operator",
                        "text": "Отчёт в разделе документов. До свидания!",
                    },
                ],
            }
        )
    )


@pytest.fixture
def checklist():
    return default_checklist()


@pytest.fixture
def judgments(checklist):
    # Mechanical scoring fixture, NOT expert labels for the synthetic transcript above.
    return ModelResponse(
        judgments=[
            Judgment(
                criterion_id=c.id,
                decision="score" if c.kind == "scale" else "yes",
                score=max(s.value for s in c.scale) if c.kind == "scale" else None,
                explanation="Test-only judgment; not a Ground Truth annotation.",
                evidence_message_ids=["m0003"],
                checked_range=CheckedRange(start_message_id="m0001", end_message_id="m0005"),
                na_reason=None,
            )
            for c in checklist.criteria
        ]
    )
