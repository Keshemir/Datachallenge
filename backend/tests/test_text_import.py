import json

import httpx
import pytest
from test_api import Settings, TestClient

from cqa.api import create_app
from cqa.provider import OpenAICompatibleProvider, ProviderError, ProviderReply
from cqa.text_import import SpeakerSpan, SpeakerSpans, assemble_turns


def span(start, end, speaker="client", review=False):
    return SpeakerSpan(
        start_line=start, end_line=end, speaker=speaker, needs_review=review, note=""
    )


def test_ranges_preserve_text_and_flag_unknown():
    lines = ["Здравствуйте!", "Где мой отчёт?", "Откройте документы.", "Неясный фрагмент"]
    result = assemble_turns(
        lines,
        SpeakerSpans(
            language="RU", spans=[span(1, 2), span(3, 3, "operator"), span(4, 4, "unknown")]
        ),
    )
    assert "\n".join(t["text"] for t in result) == "\n".join(lines)
    assert result[-1]["speaker"] == "" and result[-1]["needs_review"] is True
    assert all(t["timestamp"] == "" for t in result)


@pytest.mark.parametrize(
    "spans", [[span(2, 2)], [span(1, 1)], [span(1, 2), span(2, 2)], [span(1, 3)]]
)
def test_missing_duplicate_reordered_lines_rejected(spans):
    with pytest.raises(ProviderError):
        assemble_turns(["first", "second"], SpeakerSpans(language="RU", spans=spans))


def test_parse_endpoint_auth_limits_and_no_automatic_save(tmp_path, monkeypatch):
    async def complete(self, messages, response_model):
        assert response_model is SpeakerSpans
        assert "недоверенные" in messages[0]["content"]
        assert len(json.loads(messages[1]["content"])["untrusted_lines"]) == 2
        return ProviderReply(
            SpeakerSpans(language="RU", spans=[span(1, 1), span(2, 2, "operator")]),
            self.model,
            None,
            {},
            0,
        )

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", complete)
    settings = Settings(
        db_path=tmp_path / "test.sqlite3", llm_api_key="test-only", llm_model="test-only"
    )
    with TestClient(create_app(settings)) as client:
        request = {"text": "Где отчёт?\nОткройте документы.", "language": "RU"}
        response = client.post("/api/conversations/parse-text", json=request)
        assert response.status_code == 200
        assert response.json()["language"] == "RU"
        assert [t["speaker"] for t in response.json()["turns"]] == ["client", "operator"]
        assert client.get("/api/conversations").json() == []
        assert (
            client.post("/api/conversations/parse-text", json={"text": "x" * 50001}).status_code
            == 422
        )
        client.post("/api/conversations/parse-text", json=request)
        assert client.post("/api/conversations/parse-text", json=request).status_code == 429
        client.post("/api/auth/logout", json={})
        assert client.post("/api/conversations/parse-text", json=request).status_code == 401


def test_generic_provider_validates_import_schema():
    import asyncio

    def handler(request):
        body = json.loads(request.content)
        assert body["response_format"]["json_schema"]["schema"] == SpeakerSpans.model_json_schema()
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": '{"spans": []}'}}]},
        )

    provider = OpenAICompatibleProvider(
        "https://example.com/v1", "test", "test", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ProviderError):
        asyncio.run(provider.complete([], SpeakerSpans))


@pytest.mark.parametrize("language", ["RU", "KZ", "EN"])
def test_auto_language_comes_from_validated_model_response(tmp_path, monkeypatch, language):
    async def complete(self, messages, response_model):
        assert json.loads(messages[1]["content"])["language"] == "AUTO"
        return ProviderReply(
            SpeakerSpans(language=language, spans=[span(1, 1, "operator")]), self.model, None, {}, 0
        )

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", complete)
    with TestClient(
        create_app(Settings(db_path=tmp_path / "s.db", llm_api_key="test", llm_model="test"))
    ) as client:
        result = client.post("/api/conversations/parse-text", json={"text": "A source line"})
        assert result.status_code == 200
        assert result.json()["language"] == language
        assert result.json()["turns"][0]["text"] == "A source line"


@pytest.mark.parametrize("detected, expected", [("rus", "RU"), ("kk", "KZ"), ("eng", "EN")])
def test_audio_role_confirmation_uses_stt_language(detected, expected):
    from cqa.transcription import RoleAssignment, to_conversation

    record = {
        "id": "test",
        "detected_language": detected,
        "turns": [{"id": "t1", "speaker": "0", "start": 0, "end": 1, "text": "Source speech"}],
    }
    assignment = RoleAssignment(speaker_roles={"0": "operator"}, confirmed=True)
    assert to_conversation(record, assignment).language == expected
