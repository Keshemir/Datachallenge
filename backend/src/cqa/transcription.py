import json
from datetime import UTC, datetime
from math import isfinite
from typing import Literal
from uuid import uuid4

import httpx
from pydantic import model_validator

from .audio import AudioAsset
from .inputs import fingerprint, normalize_conversation
from .models import ConversationInput, Model, Number, Text
from .openrouter import post_openrouter, reported_cost
from .provider import ProviderError


class SpeechTurn(Model):
    id: str
    speaker: str | None
    start: Number
    end: Number
    text: Text

    @model_validator(mode="after")
    def valid_interval(self):
        if self.end < self.start:
            raise ValueError("Turn end precedes start")
        return self


class RoleAssignment(Model):
    language: Literal["RU", "KZ", "EN"] | None = None
    speaker_roles: dict[str, Literal["client", "operator", "bot"]]
    confirmed: bool = False


def parse_turns(body: dict, duration: float) -> list[SpeechTurn]:
    """Group original word strings; never rewrite or improve the transcript."""
    words = body.get("words")
    raw = words if isinstance(words, list) and words else body.get("segments", [])
    if not isinstance(raw, list) or not raw:
        raise ProviderError("STT returned no timestamped speech")
    turns: list[SpeechTurn] = []
    previous_start = -1.0
    try:
        for item in raw:
            start, end = float(item["start"]), float(item["end"])
            if not (isfinite(start) and isfinite(end) and 0 <= start <= end <= duration + 2):
                raise ValueError("Invalid timestamp")
            if start < previous_start:
                raise ValueError("Speech timestamps are not ordered")
            previous_start = start
            text = item.get("word", item.get("text", ""))
            if not isinstance(text, str) or not text.strip():
                continue
            speaker = item.get("speaker")
            if speaker is None:
                speaker = item.get("speaker_id", item.get("speaker_label"))
            if speaker is not None and type(speaker) not in (str, int):
                raise ValueError("Invalid speaker label")
            speaker = str(speaker) if speaker is not None else None
            if turns and turns[-1].speaker == speaker and start - turns[-1].end < 2:
                turns[-1].text += " " + text
                turns[-1].end = max(turns[-1].end, end)
            else:
                turns.append(
                    SpeechTurn(
                        id=f"t{len(turns) + 1:04d}",
                        speaker=speaker,
                        start=start,
                        end=end,
                        text=text,
                    )
                )
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise ProviderError("STT returned invalid timestamps or speaker data") from exc
    if not turns:
        raise ProviderError("STT returned no usable speech")
    return turns


class ScribeProvider:
    def __init__(
        self,
        key: str,
        model: str = "elevenlabs/scribe-v2",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.key, self.model, self.transport = key, model, transport

    async def transcribe(
        self, audio: AudioAsset, language: str | None, source_hash: str | None = None
    ) -> dict:
        data = {
            "model": self.model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "word",
            "provider": json.dumps(
                {
                    "options": {
                        "elevenlabs": {
                            "diarize": True,
                            "no_verbatim": False,
                            "tag_audio_events": False,
                        }
                    }
                }
            ),
        }
        if language:
            data["language"] = {"RU": "ru", "KZ": "kk", "EN": "en"}[language]
        body = await post_openrouter(
            "/api/v1/audio/transcriptions",
            self.key,
            data=data,
            files={"file": (f"audio.{audio.format}", audio.content, "application/octet-stream")},
            transport=self.transport,
        )
        turns = parse_turns(body, audio.duration)
        return {
            "id": str(uuid4()),
            "created_at": datetime.now(UTC).isoformat(),
            "model": self.model,
            "source_conversation_hash": source_hash,
            "audio_sha256": audio.sha256,
            "audio_format": audio.format,
            "duration_seconds": audio.duration,
            "detected_language": body.get("language"),
            "requested_language": language,
            "cost_usd": reported_cost(body),
            "turns": [t.model_dump() for t in turns],
            "raw_response": body,
            "speaker_ids": sorted({t.speaker for t in turns if t.speaker is not None}),
            "has_unassigned_speech": any(t.speaker is None for t in turns),
            "request_hash": fingerprint({"audio_sha256": audio.sha256, "options": data}),
        }


def to_conversation(record: dict, assignment: RoleAssignment):
    detected = str(record.get("detected_language") or "").lower()
    language = (
        assignment.language
        or record.get("requested_language")
        or {
            "ru": "RU",
            "rus": "RU",
            "russian": "RU",
            "kk": "KZ",
            "kaz": "KZ",
            "kazakh": "KZ",
            "en": "EN",
            "eng": "EN",
            "english": "EN",
        }.get(detected)
    )
    if language not in ("RU", "KZ", "EN"):
        raise ValueError(
            "The recording language could not be identified as Russian, Kazakh or English"
        )
    turns = [SpeechTurn.model_validate(t) for t in record["turns"]]
    if not assignment.confirmed:
        raise ValueError("Confirm speaker roles before creating an evaluable transcript")
    speakers = {t.speaker for t in turns}
    if None in speakers or speakers != set(assignment.speaker_roles):
        raise ValueError("Map every speaker exactly; unlabelled speech requires review")
    if "operator" not in assignment.speaker_roles.values():
        raise ValueError("At least one speaker must be assigned the operator role")

    def timestamp(seconds):
        millis = round(seconds * 1000)
        minutes, rest = divmod(millis, 60000)
        return f"{minutes:02d}:{rest // 1000:02d}.{rest % 1000:03d}"

    source = ConversationInput(
        conversation_id=f"stt-{record['id']}",
        channel="voice call",
        language=language,
        transcript=[
            {
                "timestamp": timestamp(t.start),
                "speaker": assignment.speaker_roles[t.speaker],
                "text": t.text,
            }
            for t in turns
        ],
    )
    return normalize_conversation(source)
