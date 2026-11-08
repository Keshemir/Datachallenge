from concurrent.futures import ThreadPoolExecutor

from test_api import Settings, TestClient, TestProvider, import_single

from cqa.api import create_app


def setup_evaluation(client, conversation):
    key = import_single(client, conversation)
    rubric = client.get("/api/checklists").json()[0]
    result = client.post(
        "/api/evaluations", json={"conversation_hash": key, "checklist_hash": rubric["hash"]}
    )
    assert result.status_code == 201
    return result.json(), rubric


def test_appeal_lifecycle_preserves_ai_and_recalculates(tmp_path, conversation, judgments):
    settings = Settings(db_path=tmp_path / "qa.sqlite3")
    with TestClient(create_app(settings, TestProvider(judgments))) as client:
        original, rubric = setup_evaluation(client, conversation)
        c = next(c for c in original["result"]["criteria"] if c["kind"] == "binary")
        submission = {
            "evaluation_id": original["id"],
            "criterion_id": c["criterion_id"],
            "author": "Оператор",
            "reason": "Прошу проверить приветствие.",
        }
        response = client.post("/api/appeals", json=submission)
        assert response.status_code == 201
        appeal = response.json()
        assert client.post("/api/appeals", json=submission).status_code == 409
        correction = {
            **c["judgment"],
            "decision": "no",
            "score": None,
            "explanation": "Полное приветствие отсутствует.",
            "evidence_message_ids": [],
        }
        resolution = {
            "reviewer": "QA",
            "outcome": "accepted",
            "note": "Согласовано по полному диалогу.",
            "judgment": correction,
        }
        assert (
            client.post(f"/api/appeals/{appeal['id']}/resolve", json=resolution).status_code == 409
        )
        assert (
            client.post(f"/api/appeals/{appeal['id']}/start", json={"reviewer": "QA"}).status_code
            == 200
        )
        bad = {
            **resolution,
            "judgment": {**correction, "decision": "yes", "evidence_message_ids": ["missing"]},
        }
        assert client.post(f"/api/appeals/{appeal['id']}/resolve", json=bad).status_code == 422
        assert client.get("/api/qa-reviews").json() == []
        response = client.post(f"/api/appeals/{appeal['id']}/resolve", json=resolution)
        assert response.status_code == 200
        assert [e["status"] for e in response.json()["events"]] == [
            "submitted",
            "in_review",
            "accepted",
        ]
        review = client.get("/api/qa-reviews").json()[0]
        assert review["result"]["total_score"] < original["result"]["total_score"]
        assert client.get(f"/api/evaluations/{original['id']}").json() == original
        assert (
            client.post(f"/api/appeals/{appeal['id']}/resolve", json=resolution).status_code == 409
        )
        # A separate criterion correction must retain the first accepted correction.
        flag = next(c for c in original["result"]["criteria"] if c["kind"] == "flag")
        second = client.post(
            "/api/appeals", json={**submission, "criterion_id": flag["criterion_id"]}
        ).json()
        client.post(f"/api/appeals/{second['id']}/start", json={"reviewer": "QA 2"})
        client.post(
            f"/api/appeals/{second['id']}/resolve",
            json={**resolution, "judgment": {**flag["judgment"], "decision": "no"}},
        )
        latest = client.get("/api/qa-reviews").json()[0]
        assert latest["previous_review_id"] == review["id"]
        assert latest["result"]["total_score"] == review["result"]["total_score"]
        assert latest["result"]["flagged_criteria"] == []
    # Persisted history survives application restart.
    with TestClient(create_app(settings)) as client:
        assert len(client.get("/api/qa-reviews").json()) == 2
        assert len(client.get("/api/appeals").json()) == 2


def test_rejected_appeal_and_invalid_submission(tmp_path, conversation, judgments):
    with TestClient(
        create_app(Settings(db_path=tmp_path / "qa.sqlite3"), TestProvider(judgments))
    ) as client:
        original, _ = setup_evaluation(client, conversation)
        payload = {
            "evaluation_id": original["id"],
            "criterion_id": "missing",
            "author": "Оператор",
            "reason": "Проверка",
        }
        assert client.post("/api/appeals", json=payload).status_code == 422
        payload["criterion_id"] = original["result"]["criteria"][0]["criterion_id"]
        assert client.post("/api/appeals", json={**payload, "author": "   "}).status_code == 422
        a = client.post("/api/appeals", json=payload).json()
        client.post(f"/api/appeals/{a['id']}/start", json={"reviewer": "QA"})
        result = client.post(
            f"/api/appeals/{a['id']}/resolve",
            json={
                "reviewer": "QA",
                "outcome": "rejected",
                "note": "Цитата подтверждает исходный вывод.",
            },
        )
        assert result.status_code == 200
        assert result.json()["status"] == "rejected"
        assert client.get("/api/qa-reviews").json() == []
        client.post("/api/auth/logout", json={})
        for path in ["/api/appeals", "/api/qa-reviews"]:
            assert client.get(path).status_code == 401


def test_concurrent_resolution_only_one_snapshot(tmp_path, conversation, judgments):
    with TestClient(
        create_app(Settings(db_path=tmp_path / "qa.sqlite3"), TestProvider(judgments))
    ) as client:
        original, _ = setup_evaluation(client, conversation)
        criterion = original["result"]["criteria"][0]
        a = client.post(
            "/api/appeals",
            json={
                "evaluation_id": original["id"],
                "criterion_id": criterion["criterion_id"],
                "author": "Оператор",
                "reason": "Проверка",
            },
        ).json()
        client.post(f"/api/appeals/{a['id']}/start", json={"reviewer": "QA"})

        def resolve():
            return client.post(
                f"/api/appeals/{a['id']}/resolve",
                json={
                    "reviewer": "QA",
                    "outcome": "accepted",
                    "note": "Уточнение",
                    "judgment": criterion["judgment"],
                },
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(lambda _: resolve(), range(2))) == [200, 409]
        assert len(client.get("/api/qa-reviews").json()) == 1


def test_updated_checklist_is_used_and_old_version_stays_immutable(
    tmp_path, conversation, judgments
):
    with TestClient(
        create_app(Settings(db_path=tmp_path / "qa.sqlite3"), TestProvider(judgments))
    ) as client:
        original, rubric = setup_evaluation(client, conversation)
        updated = {**rubric["checklist"], "version": 2}
        updated["criteria"][0]["weight"] = 50
        saved = client.post("/api/checklists", json=updated)
        assert saved.status_code == 201
        newer = client.post(
            "/api/evaluations",
            json={
                "conversation_hash": original["conversation_hash"],
                "checklist_hash": saved.json()["hash"],
            },
        )
        assert newer.status_code == 201
        assert newer.json()["result"]["criteria"][0]["weight"] == 50
        assert client.get(f"/api/evaluations/{original['id']}").json() == original
        updated["criteria"][0]["weight"] = 60
        assert client.post("/api/checklists", json=updated).status_code == 409
