from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .audio import MAX_AUDIO_BYTES, AudioError, download_audio, inspect_audio
from .decisions import DecisionProvider
from .models import Model, Text
from .operations import transcribe_audio, verify_saved
from .provider import ProviderError
from .settings import Settings
from .storage import Store
from .transcription import RoleAssignment, ScribeProvider, to_conversation


class TranscriptionRequest(Model):
    conversation_hash: Text


class VerifyRequest(Model):
    evaluation_id: Text


def extension_router(store: Store, settings: Settings, stt=None, decision=None) -> APIRouter:
    router = APIRouter(prefix="/api")
    stt = stt or (
        ScribeProvider(settings.llm_api_key, settings.stt_model) if settings.llm_api_key else None
    )
    decision = decision or (
        DecisionProvider(settings.llm_api_key, settings.decision_model)
        if settings.llm_api_key
        else None
    )

    @router.get("/transcriptions")
    def transcriptions():
        records = store.list_records("transcriptions")
        return [
            {k: v for k, v in r.items() if k not in ("raw_response", "turns")}
            | {"display_name": f"Запись №{len(records) - index}"}
            for index, r in enumerate(records)
        ]

    @router.post("/transcriptions", status_code=201)
    async def transcribe_source(request: TranscriptionRequest):
        if stt is None:
            raise HTTPException(503, "Configure the OpenRouter API key for STT")
        conversation = store.conversation(request.conversation_hash)
        if conversation is None:
            raise HTTPException(404, "Conversation not found")
        if not conversation.audio_url:
            raise HTTPException(422, "Conversation has no audio source")
        try:
            audio = await download_audio(conversation.audio_url, settings.audio_hosts)
            record = await transcribe_audio(
                store, stt, audio, conversation.language, request.conversation_hash
            )
            return {k: v for k, v in record.items() if k != "raw_response"}
        except AudioError as exc:
            raise HTTPException(422, str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc

    @router.post("/transcriptions/upload", status_code=201)
    async def transcribe_upload(
        file: UploadFile = File(...), language: Literal["RU", "KZ", "EN"] | None = Form(None)
    ):
        if stt is None:
            raise HTTPException(503, "Configure the OpenRouter API key for STT")
        try:
            audio = inspect_audio(await file.read(MAX_AUDIO_BYTES + 1))
            record = await transcribe_audio(store, stt, audio, language)
            return {k: v for k, v in record.items() if k != "raw_response"}
        except AudioError as exc:
            raise HTTPException(422, str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        finally:
            await file.close()

    @router.get("/transcriptions/{key}")
    def transcription(key: str):
        record = store.transcription(key)
        if record is None:
            raise HTTPException(404, "Transcription not found")
        derived = store.transcription_derivation(key)
        return {k: v for k, v in record.items() if k != "raw_response"} | {
            "speaker_roles": derived["assignment"]["speaker_roles"] if derived else {}
        }

    @router.get("/transcriptions/{key}/audio")
    def recording(key: str):
        record = store.transcription(key)
        if record is None:
            raise HTTPException(404, "Transcription not found")
        path = store.path.parent / "audio" / f"{record['audio_sha256']}.{record['audio_format']}"
        if not path.is_file():
            raise HTTPException(404, "Audio file is unavailable")
        media_types = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "flac": "audio/flac",
            "m4a": "audio/mp4",
            "ogg": "audio/ogg",
        }
        return FileResponse(path, media_type=media_types[record["audio_format"]])

    @router.post("/transcriptions/{key}/conversation", status_code=201)
    def confirm_roles(key: str, assignment: RoleAssignment):
        record = store.transcription(key)
        if record is None:
            raise HTTPException(404, "Transcription not found")
        try:
            conversation = to_conversation(record, assignment)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        digest = store.save_derivation(conversation, key, assignment.model_dump())
        return {"hash": digest, "conversation": conversation, "transcription_id": key}

    @router.get("/evaluations")
    def evaluations():
        return [
            {
                k: r[k]
                for k in (
                    "id",
                    "conversation_hash",
                    "checklist_hash",
                    "model",
                    "created_at",
                    "cost_usd",
                )
            }
            | {
                "total_score": r["result"]["total_score"],
                "flagged_criteria": r["result"]["flagged_criteria"],
            }
            for r in store.list_records("evaluations")
        ]

    @router.post("/decision-checks", status_code=201)
    async def check(request: VerifyRequest):
        if decision is None:
            raise HTTPException(503, "Configure the OpenRouter API key for Decisions")
        evaluation = store.evaluation(request.evaluation_id)
        if evaluation is None:
            raise HTTPException(404, "Evaluation not found")
        try:
            result = await verify_saved(store, decision, evaluation)
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        return {k: v for k, v in result.items() if k != "raw_response"}

    @router.get("/decision-checks")
    def checks():
        return [
            {k: v for k, v in r.items() if k != "raw_response"}
            for r in store.list_records("decision_checks")
        ]

    @router.get("/usage")
    def usage():
        records = store.list_records("external_calls")
        return {
            "reported_cost_usd": sum(r["cost_usd"] or 0 for r in records),
            "calls_with_unknown_cost": sum(r["cost_usd"] is None for r in records),
            "calls": records,
        }

    return router
