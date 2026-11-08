import asyncio
import io
import json
import wave

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cqa.audio import AudioError, download_audio, inspect_audio
from cqa.decisions import DecisionProvider, choices_for, decision_payload, validate_answers
from cqa.extensions import extension_router
from cqa.inputs import fingerprint
from cqa.operations import evaluate_saved, tracked_call, transcribe_audio, verify_saved
from cqa.provider import ProviderError, ProviderReply
from cqa.settings import Settings
from cqa.storage import Store
from cqa.transcription import RoleAssignment, ScribeProvider, parse_turns, to_conversation


def wav_bytes():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\0\0" * 16000)
    return stream.getvalue()


def stt_body():
    return {
        "language": "rus",
        "text": "Здравствуйте! Спасибо.",
        "words": [
            {"word": "Здравствуйте!", "start": 0, "end": 0.8, "speaker": 1},
            {"word": "Спасибо.", "start": 1.0, "end": 1.9, "speaker": 0},
        ],
        "usage": {"cost": 0.001},
    }


def decision_body(checklist):
    answers = {}
    for c in checklist.criteria:
        options = choices_for(c)
        choice = next(iter(options))
        answers[c.id] = {
            "type": "choice",
            "choice": choice,
            "probabilities": {k: float(k == choice) for k in options},
            "confidence": 1,
        }
    return {"answers": answers, "usage": {"cost": 0.0001}}


def test_audio_metadata_and_invalid_file():
    audio = inspect_audio(wav_bytes())
    assert audio.duration == 2
    assert audio.format == "wav"
    with pytest.raises(AudioError):
        inspect_audio(b"<html>not audio</html>")


def test_resolve_player_and_preserve_audio():
    def handler(request):
        if request.url.path == "/player":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text='<audio src="/recording?sig=secret"></audio>',
            )
        return httpx.Response(200, content=wav_bytes(), headers={"content-type": "audio/wav"})

    result = asyncio.run(
        download_audio("https://media.test/player", ("media.test",), httpx.MockTransport(handler))
    )
    assert result.content == wav_bytes()


def test_audio_redirect_cannot_escape_allowed_hosts():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://127.0.0.1/private"})

    with pytest.raises(AudioError, match="not allowed"):
        asyncio.run(
            download_audio(
                "https://media.test/player", ("media.test",), httpx.MockTransport(handler)
            )
        )
    assert len(seen) == 1


def test_stt_request_speakers_and_cost():
    def handler(request):
        assert request.url.path == "/api/v1/audio/transcriptions"
        content = request.content.decode("utf-8", errors="replace")
        assert '"diarize": true' in content
        assert '"no_verbatim": false' in content
        assert "verbose_json" in content
        return httpx.Response(200, json=stt_body())

    provider = ScribeProvider("test-key", transport=httpx.MockTransport(handler))
    record = asyncio.run(provider.transcribe(inspect_audio(wav_bytes()), "RU"))
    assert record["speaker_ids"] == ["0", "1"]
    assert record["cost_usd"] == 0.001
    assert record["has_unassigned_speech"] is False
    with pytest.raises(ValueError, match="Confirm"):
        to_conversation(
            record, RoleAssignment(language="RU", speaker_roles={"0": "client", "1": "operator"})
        )
    derived = to_conversation(
        record,
        RoleAssignment(
            language="RU", confirmed=True, speaker_roles={"0": "client", "1": "operator"}
        ),
    )
    assert derived.transcript[0].speaker == "operator"
    assert derived.transcript[0].timestamp == "00:00.000"
    assert all(t.speaker != "system" for t in derived.transcript)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["words"][0].update(start=-1),
        lambda b: b["words"][0].update(end=999),
        lambda b: b["words"][0].update(start=float("nan")),
        lambda b: b["words"][0].update(speaker={"bad": True}),
    ],
)
def test_invalid_stt_rejected(mutate):
    body = stt_body()
    mutate(body)
    with pytest.raises(ProviderError):
        parse_turns(body, 2)


def test_unlabelled_speech_cannot_be_assigned_arbitrarily():
    body = stt_body()
    del body["words"][0]["speaker"]
    record = {"id": "test", "turns": [t.model_dump() for t in parse_turns(body, 2)]}
    with pytest.raises(ValueError, match="every speaker"):
        to_conversation(
            record, RoleAssignment(language="RU", confirmed=True, speaker_roles={"0": "operator"})
        )


def test_decisions_use_discrete_choices_and_no_prior_answer(conversation, checklist):
    payload = decision_payload(conversation, checklist, "test-model")
    assert set(payload["questions"]["management"]["criteria"]) == {
        "score_0",
        "score_4",
        "score_7",
        "score_10",
    }
    assert "na" in payload["questions"]["consultation"]["criteria"]
    assert "audio_url" not in payload["state"]["untrusted_transcript"]
    assert all(q["type"] == "choice" for q in payload["questions"].values())
    assert "evaluation" not in json.dumps(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["answers"].pop("contact"),
        lambda b: b["answers"]["contact"].update(choice="na"),
        lambda b: b["answers"]["contact"].update(type="score"),
        lambda b: b["answers"]["contact"]["probabilities"].update(yes=float("nan")),
        lambda b: b["answers"]["contact"]["probabilities"].update(yes=0.5),
    ],
)
def test_invalid_decisions_rejected(checklist, mutate):
    body = decision_body(checklist)
    mutate(body)
    with pytest.raises(ProviderError):
        validate_answers(body, checklist)


def test_saved_pipeline_and_api_no_overwrite(tmp_path, conversation, checklist, judgments):
    store = Store(tmp_path / "test.sqlite3")
    store.initialize()
    source_key = store.save_conversations([conversation])[0]
    store.save_checklist(checklist)

    class MainProvider:
        model = "test-model"

        async def judge(self, messages):
            return ProviderReply(judgments, self.model, None, {}, 0.01)

    main = asyncio.run(evaluate_saved(store, MainProvider(), conversation, checklist))
    checker = DecisionProvider(
        "test-key",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json=decision_body(checklist))
        ),
    )
    check = asyncio.run(verify_saved(store, checker, main))
    assert len(check["disagreements"]) == 2  # lowest scale levels vs maximum in fixture
    assert store.evaluation(main["id"]) == main
    assert check["changes_final_score"] is False
    stt = ScribeProvider(
        "test-key", transport=httpx.MockTransport(lambda req: httpx.Response(200, json=stt_body()))
    )
    record = asyncio.run(transcribe_audio(store, stt, inspect_audio(wav_bytes()), "RU", source_key))
    app = FastAPI()
    app.include_router(
        extension_router(store, Settings(db_path=store.path), stt=stt, decision=checker)
    )
    with TestClient(app) as client:
        response = client.post(
            f"/api/transcriptions/{record['id']}/conversation",
            json={
                "language": "RU",
                "speaker_roles": {"0": "client", "1": "operator"},
                "confirmed": True,
            },
        )
        assert response.status_code == 201
        assert response.json()["hash"] != fingerprint(conversation)
        summary = next(
            c for c in store.list_conversations() if c["hash"] == response.json()["hash"]
        )
        assert summary["transcription_id"] == record["id"]
        assert summary["preview"]
        assert store.conversation(source_key) == conversation
        assert client.get(f"/api/transcriptions/{record['id']}/audio").content == wav_bytes()
        assert "raw_response" not in client.get(f"/api/transcriptions/{record['id']}").json()
        assert client.get("/api/usage").json()["reported_cost_usd"] == pytest.approx(0.0111)
        response = client.post(
            "/api/transcriptions/upload",
            files={"file": ("test.wav", wav_bytes())},
            data={"language": "RU"},
        )
        assert response.status_code == 201


def test_failed_call_does_not_claim_zero_cost(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    store.initialize()

    async def fail():
        raise ProviderError("test error")

    with pytest.raises(ProviderError):
        asyncio.run(tracked_call(store, "test", "test-model", fail))
    record = store.list_records("external_calls")[0]
    assert record["status"] == "failed"
    assert record["cost_usd"] is None
