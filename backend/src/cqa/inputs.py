import hashlib
import json
from importlib.resources import files

from .models import Checklist, Conversation, ConversationInput, Message, Model


def canonical_json(value: Model | dict | list) -> str:
    data = value.model_dump(mode="json") if isinstance(value, Model) else value
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def fingerprint(value: Model | dict | list) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_conversation(source: ConversationInput) -> Conversation:
    # Preserve original order, text and timestamp precision (including ISO 8601 offsets).
    return Conversation(
        **source.model_dump(exclude={"transcript"}),
        transcript=[
            Message(**turn.model_dump(), message_id=f"m{i:04d}")
            for i, turn in enumerate(source.transcript, 1)
        ],
    )


def default_checklist() -> Checklist:
    raw = files("cqa").joinpath("rubrics/freedom-chat-v1.json").read_text(encoding="utf-8")
    return Checklist.model_validate_json(raw)
