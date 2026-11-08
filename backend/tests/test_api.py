import sqlite3

from fastapi.testclient import TestClient as RawTestClient

from cqa.api import create_app
from cqa.inputs import default_checklist, fingerprint
from cqa.provider import ProviderError, ProviderReply
from cqa.security import hash_password
from cqa.settings import Settings as AppSettings

TEST_PASSWORD = "unit-test-password-123"
TEST_HASH = hash_password(TEST_PASSWORD)


def Settings(**kwargs):
    return AppSettings(password_hash=TEST_HASH, **kwargs)


class TestClient(RawTestClient):
    __test__ = False

    def __init__(self, app):
        super().__init__(
            app,
            base_url="http://localhost:8000",
            headers={"Origin": "http://localhost:8000", "X-CQA-Request": "1"},
        )

    def __enter__(self):
        super().__enter__()
        response = self.post("/api/auth/login", json={"password": TEST_PASSWORD})
        assert response.status_code == 200
        self.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return self


class TestProvider:
    __test__ = False
    model = "test-only-model"

    def __init__(self, response):
        self.response = response
        self.calls = 0

    async def judge(self, messages):
        self.calls += 1
        return ProviderReply(self.response, self.model, "test-request", {"total_tokens": 20}, 0)


def import_single(client, conversation):
    source = conversation.model_dump()
    for turn in source["transcript"]:
        del turn["message_id"]
    response = client.post("/api/conversations", json=source)
    assert response.status_code == 201
    return response.json()["hash"]


def test_health_and_missing_provider(tmp_path, conversation):
    settings = Settings(db_path=tmp_path / "test.sqlite3")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").json()["evaluation_ready"] is False
        key = import_single(client, conversation)
        rubric = client.get("/api/checklists").json()[0]
        result = client.post(
            "/api/evaluations", json={"conversation_hash": key, "checklist_hash": rubric["hash"]}
        )
        assert result.status_code == 503


def test_complete_api_flow_and_persistence(tmp_path, conversation, judgments):
    settings = Settings(db_path=tmp_path / "test.sqlite3")
    provider = TestProvider(judgments)
    with TestClient(create_app(settings, provider)) as client:
        key = import_single(client, conversation)
        assert import_single(client, conversation) == key
        assert len(client.get("/api/conversations").json()) == 1
        rubric = client.get("/api/checklists").json()[0]
        request = {"conversation_hash": key, "checklist_hash": rubric["hash"]}
        result = client.post("/api/evaluations", json=request)
        assert result.status_code == 201, result.text
        record = result.json()
        assert record["result"]["total_score"] == 100
        assert record["model"] == "test-only-model"
        assert record["cost_usd"] == 0
        assert record["prompt_version"]
        second = client.post("/api/evaluations", json=request).json()
        assert second["id"] != record["id"]
        assert second["request_hash"] == record["request_hash"]
        assert provider.calls == 2
    with TestClient(create_app(settings, provider)) as client:
        assert client.get(f"/api/evaluations/{record['id']}").json() == record
        assert (
            client.get(f"/api/conversations/{key}").json()["conversation"]["transcript"][0][
                "message_id"
            ]
            == "m0001"
        )


def test_changed_checklist_version_requires_new_snapshot(tmp_path):
    with TestClient(create_app(Settings(db_path=tmp_path / "test.sqlite3"))) as client:
        original = client.get("/api/checklists").json()[0]
        changed = original["checklist"]
        changed["criteria"][0]["instructions"] = "New instructions"
        assert client.post("/api/checklists", json=changed).status_code == 409
        changed["version"] = 2
        result = client.post("/api/checklists", json=changed)
        assert result.status_code == 201
        assert result.json()["hash"] != original["hash"]
        assert len(client.get("/api/checklists").json()) == 2
        assert (
            client.get("/api/checklists").json()[0]["checklist"]["criteria"][0]["instructions"]
            != "New instructions"
        )


def test_invalid_model_judgments_not_saved(tmp_path, conversation, judgments):
    db_path = tmp_path / "test.sqlite3"
    judgments.judgments.pop()
    with TestClient(create_app(Settings(db_path=db_path), TestProvider(judgments))) as client:
        key = import_single(client, conversation)
        result = client.post(
            "/api/evaluations",
            json={"conversation_hash": key, "checklist_hash": fingerprint(default_checklist())},
        )
        assert result.status_code == 502
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT count(*) FROM evaluations").fetchone()[0] == 0


def test_dataset_count_mismatch_is_atomic(tmp_path, conversation):
    source = conversation.model_dump()
    for turn in source["transcript"]:
        del turn["message_id"]
    envelope = {
        "error": "",
        "isSuccess": True,
        "data": {"dataset_group_id": "TEST", "total_records": 2, "records": [source]},
    }
    with TestClient(create_app(Settings(db_path=tmp_path / "test.sqlite3"))) as client:
        assert client.post("/api/conversations/import", json=envelope).status_code == 422
        assert client.get("/api/conversations").json() == []
        envelope["data"]["total_records"] = 1
        assert client.post("/api/conversations/import", json=envelope).status_code == 201


def test_provider_failure_surfaces_without_fake_scores(tmp_path, conversation):
    class FailedProvider:
        model = "failed-test-model"

        async def judge(self, messages):
            raise ProviderError("Model provider is unavailable")

    with TestClient(
        create_app(Settings(db_path=tmp_path / "test.sqlite3"), FailedProvider())
    ) as client:
        key = import_single(client, conversation)
        result = client.post(
            "/api/evaluations",
            json={"conversation_hash": key, "checklist_hash": fingerprint(default_checklist())},
        )
        assert result.status_code == 502
        assert "result" not in result.json()
