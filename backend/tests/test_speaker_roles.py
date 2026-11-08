import pytest
from test_api import Settings, TestClient
from test_extensions import wav_bytes

from cqa.api import create_app
from cqa.provider import OpenAICompatibleProvider, ProviderError, ProviderReply
from cqa.speaker_roles import SpeakerRole, SpeakerRoleResponse, validate_roles
from cqa.storage import Store


def record():
    return {
        "id": "role-test",
        "source_conversation_hash": None,
        "detected_language": "eng",
        "requested_language": None,
        "audio_sha256": "a" * 64,
        "audio_format": "wav",
        "speaker_ids": ["0", "1"],
        "has_unassigned_speech": False,
        "turns": [
            {
                "id": "t1",
                "speaker": "1",
                "start": 0,
                "end": 0.8,
                "text": "Hello, this is Anna from support. How can I help?",
            },
            {"id": "t2", "speaker": "0", "start": 1, "end": 1.8, "text": "Where is my statement?"},
        ],
    }


def response():
    return SpeakerRoleResponse(
        roles=[
            SpeakerRole(speaker_id="0", role="client", evidence_turn_ids=["t2"]),
            SpeakerRole(speaker_id="1", role="operator", evidence_turn_ids=["t1"]),
        ],
        needs_review=False,
        reason="",
    )


@pytest.mark.parametrize("defect", ["uncertain", "missing", "same_role", "wrong_evidence"])
def test_bad_assignments_rejected(defect):
    result = response()
    if defect == "uncertain":
        result.needs_review = True
    if defect == "missing":
        result.roles.pop()
    if defect == "same_role":
        result.roles[0].role = "operator"
    if defect == "wrong_evidence":
        result.roles[0].evidence_turn_ids = ["t1"]
    with pytest.raises(ProviderError):
        validate_roles(record(), result)


def test_auto_roles_source_preserved_cached_and_no_paid_get(tmp_path, monkeypatch):
    settings = Settings(db_path=tmp_path / "s.db", llm_api_key="test", llm_model="test")
    store = Store(settings.db_path)
    store.initialize()
    source = record()
    store.save_transcription(source, wav_bytes())
    calls = []

    async def complete(self, messages, response_model):
        calls.append(messages)
        assert response_model is SpeakerRoleResponse
        return ProviderReply(response(), self.model, None, {}, 0)

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", complete)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/transcriptions/role-test").json()["speaker_roles"] == {}
        assert not calls
        result = client.post(
            "/api/transcriptions/auto-conversation", json={"transcription_id": "role-test"}
        )
        assert result.status_code == 201
        conv = client.get("/api/conversations/" + result.json()["hash"]).json()["conversation"]
        assert [t["text"] for t in conv["transcript"]] == [t["text"] for t in source["turns"]]
        assert [t["speaker"] for t in conv["transcript"]] == ["operator", "client"]
        assert conv["language"] == "EN"
        again = client.post(
            "/api/transcriptions/auto-conversation", json={"transcription_id": "role-test"}
        )
        assert again.json()["hash"] == result.json()["hash"] and len(calls) == 1
        assert client.get("/api/transcriptions/role-test").json()["speaker_roles"] == {
            "0": "client",
            "1": "operator",
        }
        assert store.transcription("role-test") == source
        assert (
            store.transcription_derivation("role-test")["assignment"]["confirmation_source"]
            == "automatic"
        )


def test_unknown_roles_do_not_create_conversation(tmp_path, monkeypatch):
    settings = Settings(db_path=tmp_path / "s.db", llm_api_key="test", llm_model="test")
    store = Store(settings.db_path)
    store.initialize()
    store.save_transcription(record(), wav_bytes())

    async def complete(self, messages, response_model):
        answer = response()
        answer.needs_review = True
        return ProviderReply(answer, self.model, None, {}, 0)

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", complete)
    with TestClient(create_app(settings)) as client:
        assert (
            client.post(
                "/api/transcriptions/auto-conversation", json={"transcription_id": "role-test"}
            ).status_code
            == 502
        )
        assert client.get("/api/conversations").json() == []
        assert client.get("/api/transcriptions/role-test").status_code == 200
