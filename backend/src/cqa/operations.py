from datetime import UTC, datetime
from uuid import uuid4

from .audio import AudioAsset
from .decisions import DecisionProvider
from .inputs import canonical_json
from .provider import JudgeProvider, ProviderError
from .service import run_evaluation
from .storage import Store
from .transcription import ScribeProvider


async def tracked_call(store: Store, kind: str, model: str, operation):
    record = {
        "id": str(uuid4()),
        "kind": kind,
        "model": model,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "started",
        "cost_usd": None,
        "result_id": None,
    }
    store.save_call(record)
    try:
        result = await operation()
        record.update(status="succeeded", cost_usd=result.get("cost_usd"), result_id=result["id"])
        return result
    except Exception as exc:
        # Store only exception class, not upstream body, credentials, or signed URLs.
        record.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        record["finished_at"] = datetime.now(UTC).isoformat()
        store.save_call(record)


async def transcribe_audio(
    store: Store,
    provider: ScribeProvider,
    audio: AudioAsset,
    language: str | None,
    source_hash: str | None = None,
):
    async def operation():
        result = await provider.transcribe(audio, language, source_hash)
        store.save_transcription(result, audio.content)
        return result

    return await tracked_call(store, "transcription", provider.model, operation)


async def evaluate_saved(store: Store, provider: JudgeProvider, conversation, checklist):
    if len(canonical_json(conversation)) + len(canonical_json(checklist)) > 160000:
        raise ProviderError("Conversation and checklist exceed the evaluation size limit")

    async def operation():
        result = await run_evaluation(conversation, checklist, provider)
        store.save_evaluation(result)
        return result

    return await tracked_call(store, "evaluation", provider.model, operation)


async def verify_saved(store: Store, provider: DecisionProvider, evaluation: dict):
    conversation = store.conversation(evaluation["conversation_hash"])
    checklist = store.checklist(evaluation["checklist_hash"])
    if conversation is None or checklist is None:
        raise ValueError("Evaluation inputs are unavailable")
    if len(canonical_json(conversation)) + len(canonical_json(checklist)) > 160000:
        raise ProviderError("Conversation and checklist exceed the evaluation size limit")

    async def operation():
        result = await provider.verify(conversation, checklist, evaluation)
        store.save_decision_check(result)
        return result

    return await tracked_call(store, "decision_check", provider.model, operation)
