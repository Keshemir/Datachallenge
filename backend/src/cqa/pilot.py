"""Small resumable LIVE experiment. Explicit --run is required; it spends API credits."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from .audio import download_audio
from .decisions import DecisionProvider
from .inputs import default_checklist
from .operations import evaluate_saved, transcribe_audio, verify_saved
from .provider import OpenAICompatibleProvider
from .settings import ROOT, Settings
from .storage import Store
from .transcription import ScribeProvider

PILOT_IDS = ("p1-ru-001", "p1-kz-013", "p1-en-009")


class RecordingTransport(httpx.AsyncBaseTransport):
    """Archive responses, never requests/Authorization. Helps inspect charged failed calls."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.inner = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request):
        response = await self.inner.handle_async_request(request)
        body = await response.aread()
        try:
            parsed_body = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            parsed_body = {"unparsed": True}
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{uuid4()}.json").write_text(
            json.dumps(
                {
                    "endpoint": request.url.path,
                    "status": response.status_code,
                    "body": parsed_body,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return response

    async def aclose(self):
        await self.inner.aclose()


async def run(directory: Path):
    settings = Settings.from_env()
    if not settings.llm_api_key:
        raise RuntimeError("Configure the API key first")
    store = Store(settings.db_path)
    store.initialize()
    checklist = default_checklist()
    rubric_hash = store.save_checklist(checklist)
    directory.mkdir(parents=True, exist_ok=True)
    report_path = directory / "report.json"
    report = (
        json.loads(report_path.read_text(encoding="utf-8"))
        if report_path.exists()
        else {
            "created_at": datetime.now(UTC).isoformat(),
            "checklist_hash": rubric_hash,
            "purpose": "Integration pilot, not a Ground Truth accuracy benchmark",
            "transcription_id": None,
            "evaluations": [],
        }
    )
    if report["checklist_hash"] != rubric_hash:
        raise RuntimeError("Checklist changed; use a new output directory for a new experiment")

    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def transport():
        return RecordingTransport(directory / "responses")

    summaries = store.list_conversations()
    if report["transcription_id"] is None:
        summary = next(r for r in summaries if r["conversation_id"] == "p4-ru-001")
        source = store.conversation(summary["hash"])
        print("Downloading pilot audio...", flush=True)
        audio = await download_audio(source.audio_url, settings.audio_hosts)
        print(f"Transcribing {audio.duration:.1f} seconds with {settings.stt_model}...", flush=True)
        record = await transcribe_audio(
            store,
            ScribeProvider(settings.llm_api_key, settings.stt_model, transport()),
            audio,
            source.language,
            summary["hash"],
        )
        report["transcription_id"] = record["id"]
        report["audio_seconds"] = audio.duration
        report["stt_cost_usd"] = record["cost_usd"]
        save()
        print(
            f"STT saved: {len(record['turns'])} turns; speakers {record['speaker_ids']}", flush=True
        )
    for source_id in PILOT_IDS:
        existing = next(
            (e for e in report["evaluations"] if e["conversation_id"] == source_id), None
        )
        if existing is None:
            summary = next(r for r in summaries if r["conversation_id"] == source_id)
            conversation = store.conversation(summary["hash"])
            print(f"Evaluating {source_id} with {settings.llm_model}...", flush=True)
            provider = OpenAICompatibleProvider(
                settings.llm_base_url,
                settings.llm_api_key,
                settings.llm_model,
                timeout=150,
                max_output_tokens=settings.llm_max_output_tokens,
                transport=transport(),
            )
            result = await evaluate_saved(store, provider, conversation, checklist)
            existing = {
                "conversation_id": source_id,
                "evaluation_id": result["id"],
                "total_score": result["result"]["total_score"],
                "evaluation_cost_usd": result["cost_usd"],
            }
            report["evaluations"].append(existing)
            save()
        if "decision_check_id" not in existing:
            print(
                f"Checking {source_id} independently with {settings.decision_model}...", flush=True
            )
            result = await verify_saved(
                store,
                DecisionProvider(settings.llm_api_key, settings.decision_model, transport()),
                store.evaluation(existing["evaluation_id"]),
            )
            existing.update(
                decision_check_id=result["id"],
                disagreements=result["disagreements"],
                decision_cost_usd=result["cost_usd"],
            )
            save()
    update_cost_summary(report)
    report["completed_at"] = datetime.now(UTC).isoformat()
    save()
    print(
        f"Pilot complete. Report: {report_path}; reported cost ${report['reported_total_cost_usd']:.6f}",
        flush=True,
    )


def update_cost_summary(report: dict):
    costs = [report.get("stt_cost_usd")]
    for evaluation in report["evaluations"]:
        costs.extend([evaluation.get("evaluation_cost_usd"), evaluation.get("decision_cost_usd")])
    if report.get("voice_evaluation"):
        voice = report["voice_evaluation"]
        costs.extend([voice.get("evaluation_cost_usd"), voice.get("decision_cost_usd")])
    report["reported_total_cost_usd"] = sum(cost for cost in costs if cost is not None)
    report["unreported_cost_count"] = sum(cost is None for cost in costs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run", action="store_true", help="Run paid STT + three evaluations and checks"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "tmp" / "pilot")
    args = parser.parse_args()
    if not args.run:
        parser.error("Pass --run to explicitly enable paid provider calls")
    asyncio.run(run(args.output))


if __name__ == "__main__":
    main()
