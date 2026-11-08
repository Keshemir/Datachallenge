import json
import sys

import pytest
from fastapi.testclient import TestClient as RawClient
from test_api import Settings, TestClient

from cqa.api import create_app
from cqa.engine import evaluate
from cqa.inputs import fingerprint
from cqa.storage import Store
from cqa.submission import SubmissionRequest, build_submission, convert_evaluation, main


def saved(store, conversation, checklist, judgments, key="eval-1", model="actual-model"):
    result = evaluate(conversation, checklist, judgments)
    record = {
        "id": key,
        "conversation_hash": fingerprint(conversation),
        "checklist_hash": fingerprint(checklist),
        "created_at": "2026-11-07T00:00:00Z",
        "model": model,
        "result": result.model_dump(mode="json"),
    }
    store.save_evaluation(record)
    return record


def setup(store_path, conversation, checklist, judgments, count=10):
    store = Store(store_path)
    store.initialize()
    checklist_hash = store.save_checklist(checklist)
    conversations = [
        conversation.model_copy(update={"conversation_id": f"prod-{i}"}) for i in range(count)
    ]
    dataset_hash = store.save_dataset("PROD", conversations)
    for i, conv in enumerate(conversations[:-1]):
        saved(store, conv, checklist, judgments, key=f"eval-{i}")
    request = SubmissionRequest(
        dataset_hash=dataset_hash,
        checklist_hash=checklist_hash,
        split="prod",
        team_name="ClearCall",
    )
    return store, conversations, request


def test_official_example_scale_na_critical_and_original_positions(
    tmp_path, conversation, checklist, judgments
):
    store = Store(tmp_path / "s.db")
    store.initialize()
    store.save_conversations([conversation])
    store.save_checklist(checklist)
    for j in judgments.judgments:
        j.checked_range = None
        if j.criterion_id in ("needs", "identification"):
            j.decision, j.na_reason, j.evidence_message_ids = "na", "Общий вопрос.", ["m0001"]
        if j.criterion_id == "consultation":
            j.score = 15
        if j.criterion_id == "management":
            j.score = 7
    record = saved(store, conversation, checklist, judgments)
    output = convert_evaluation(conversation, checklist, record)
    by_id = {c["criterion_id"]: c for c in output["criteria"]}
    assert list(by_id) == [
        "contact",
        "discovery",
        "identification",
        "consultation",
        "empathy",
        "dialogue",
        "closure",
        "critical",
    ]
    assert by_id["contact"]["evidence_turns"] == [
        3
    ]  # Client and bot count, not operator-only index.
    assert by_id["discovery"]["value"] is None
    assert by_id["dialogue"]["value"] == 7  # Not the weighted 10.5 contribution.
    assert by_id["critical"]["value"] is True
    assert output["score"] == {"final_score": 85.38, "critical_flag": True}


def test_manifest_missing_results_and_latest_exact_evaluation(
    tmp_path, conversation, checklist, judgments
):
    store, conversations, request = setup(tmp_path / "s.db", conversation, checklist, judgments)
    unrelated = conversation.model_copy(update={"conversation_id": "uploaded-demo"})
    store.save_conversations([unrelated])
    saved(store, unrelated, checklist, judgments, "extra", "do-not-export")
    saved(store, conversations[0], checklist, judgments, "newer", "second-actual-model")
    report = build_submission(store, request)
    assert report["ready"]
    assert report["summary"] == {"total": 10, "ok": 9, "error": 1}
    assert report["payload"]["model"] == {
        "mode": "external_api",
        "name": "actual-model, second-actual-model",
    }
    missing = report["payload"]["results"][-1]
    assert missing["conversation_id"] == "prod-9"
    assert missing["status"] == "error" and missing["criteria"] == [] and missing["score"] is None
    assert report["payload"]["results"][0]["criteria"][0]["evidence_turns"] == [1, 2, 3, 4, 5]
    # A derived conversation with the same ID has different evidence positions and must not replace source.
    derived = conversations[-1].model_copy(
        update={"transcript": list(reversed(conversations[-1].transcript))}
    )
    store.save_conversations([derived])
    derived_judgments = judgments.model_copy(deep=True)
    for judgment in derived_judgments.judgments:
        judgment.checked_range = None
        judgment.evidence_message_ids = ["m0005"]
    saved(store, derived, checklist, derived_judgments, "derived", "wrong-source-model")
    assert build_submission(store, request)["summary"]["error"] == 1


@pytest.mark.parametrize("kind", ["score", "evidence", "na", "duplicate"])
def test_invalid_saved_results_become_errors_not_zero_or_old_fallback(
    tmp_path, conversation, checklist, judgments, kind
):
    store, conversations, request = setup(tmp_path / "s.db", conversation, checklist, judgments)
    record = saved(store, conversations[0], checklist, judgments, "new")
    record["id"] = "corrupt"
    if kind == "score":
        record["result"]["total_score"] = 0
    elif kind == "evidence":
        record["result"]["criteria"][0]["judgment"]["evidence_message_ids"] = ["m9999"]
    elif kind == "na":
        record["result"]["criteria"][0]["judgment"].update(decision="na", na_reason="unknown")
    else:
        record["result"]["criteria"].append(record["result"]["criteria"][0])
    store.save_evaluation(record)
    report = build_submission(store, request)
    assert report["ready"] and report["summary"]["error"] == 2
    assert report["payload"]["results"][0]["score"] is None


def test_wrong_set_shape_duplicate_ids_and_changed_rubric_block(
    tmp_path, conversation, checklist, judgments
):
    store, conversations, request = setup(
        tmp_path / "s.db", conversation, checklist, judgments, count=9
    )
    assert not build_submission(store, request)["ready"]
    request.dataset_hash = store.save_dataset("PROD", conversations + [conversations[0]])
    assert any("повторяются" in i for i in build_submission(store, request)["issues"])
    checklist.version += 1
    checklist.criteria[0].weight = 11
    request.checklist_hash = store.save_checklist(checklist)
    assert any("вес" in i for i in build_submission(store, request)["issues"])


def test_api_private_dataset_registration_and_read_only_preview(
    tmp_path, conversation, checklist, judgments
):
    settings = Settings(db_path=tmp_path / "s.db")
    store, conversations, request = setup(settings.db_path, conversation, checklist, judgments)
    with RawClient(create_app(settings), base_url="http://localhost:8000") as anonymous:
        assert anonymous.get("/api/submissions/datasets").status_code == 401
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/submissions/datasets").json()[0]["count"] == 10
        response = client.post("/api/submissions/preview", json=request.model_dump())
        assert response.status_code == 200 and response.json()["ready"]
        assert not store.list_records("external_calls")
        no_csrf = client.headers.pop("X-CSRF-Token")
        assert client.post("/api/submissions/preview", json=request.model_dump()).status_code == 403
        client.headers["X-CSRF-Token"] = no_csrf
        envelope = {
            "error": "",
            "isSuccess": True,
            "data": {
                "dataset_group_id": "new",
                "total_records": 1,
                "records": [
                    conversation.model_dump(exclude={"transcript"})
                    | {
                        "transcript": [
                            m.model_dump(exclude={"message_id"}) for m in conversation.transcript
                        ]
                    }
                ],
            },
        }
        result = client.post("/api/conversations/import", json=envelope)
        assert result.status_code == 201 and result.json()["dataset_hash"]


def test_cli_writes_utf8_expected_path_requires_error_ack_and_no_overwrite(
    tmp_path, monkeypatch, conversation, checklist, judgments
):
    store, conversations, request = setup(tmp_path / "s.db", conversation, checklist, judgments)
    path = tmp_path / "dataset.json"
    path.write_text(
        json.dumps(
            {
                "error": "",
                "isSuccess": True,
                "data": {
                    "dataset_group_id": "PROD",
                    "total_records": 10,
                    "records": [
                        c.model_dump(exclude={"transcript"})
                        | {
                            "transcript": [
                                m.model_dump(exclude={"message_id"}) for m in c.transcript
                            ]
                        }
                        for c in conversations
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("cqa.submission.Settings.from_env", lambda: Settings(db_path=store.path))
    monkeypatch.chdir(tmp_path)
    argv = [
        "submission",
        "--dataset",
        str(path),
        "--split",
        "prod",
        "--team-name",
        "Команда",
        "--checklist-hash",
        request.checklist_hash,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit):
        main()
    monkeypatch.setattr(sys, "argv", argv + ["--include-errors"])
    main()
    output = tmp_path / "results/prod/results.json"
    assert not output.read_bytes().startswith(b"\xef\xbb\xbf")
    assert json.loads(output.read_text(encoding="utf-8"))["team_name"] == "Команда"
    with pytest.raises(FileExistsError):
        main()
    assert not store.list_records("external_calls")
