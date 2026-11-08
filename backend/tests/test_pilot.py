import asyncio
import json

import httpx
import pytest

from cqa.pilot import RecordingTransport, update_cost_summary


def test_archive_parses_json_after_provider_whitespace(tmp_path):
    async def run():
        transport = RecordingTransport(tmp_path)
        await transport.inner.aclose()
        transport.inner = httpx.MockTransport(
            lambda request: httpx.Response(200, content=b'\n  {"usage":{"cost":0.25}}')
        )
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.post(
                "https://example.test/api", headers={"Authorization": "Bearer secret"}
            )
            assert response.json()["usage"]["cost"] == 0.25

    asyncio.run(run())
    saved = next(tmp_path.glob("*.json")).read_text(encoding="utf-8")
    assert json.loads(saved)["body"]["usage"]["cost"] == 0.25
    assert "secret" not in saved


def test_pilot_cost_includes_all_models_and_marks_unknown():
    report = {
        "stt_cost_usd": 0.02,
        "evaluations": [{"evaluation_cost_usd": 0.007, "decision_cost_usd": 0.0002}],
        "voice_evaluation": {"evaluation_cost_usd": 0.009, "decision_cost_usd": None},
    }
    update_cost_summary(report)
    assert report["reported_total_cost_usd"] == pytest.approx(0.0362)
    assert report["unreported_cost_count"] == 1
