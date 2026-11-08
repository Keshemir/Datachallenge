from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .appeals import appeal_router, initialize_appeals
from .engine import InvalidJudgments
from .extensions import extension_router
from .inputs import default_checklist, normalize_conversation
from .models import Checklist, ConversationInput, DatasetEnvelope, Model, Text
from .operations import evaluate_saved
from .provider import JudgeProvider, OpenAICompatibleProvider, ProviderError
from .security import SecurityMiddleware, SecurityStore, auth_router, valid_password_hash
from .settings import Settings
from .speaker_roles import speaker_role_router
from .storage import ChecklistConflict, Store
from .submission import submission_router
from .text_import import text_import_router


class EvaluationRequest(Model):
    conversation_hash: Text
    checklist_hash: Text


def create_app(settings: Settings | None = None, provider: JudgeProvider | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate_security()
    if settings.password_hash and not valid_password_hash(settings.password_hash):
        raise ValueError("CQA_PASSWORD_HASH is invalid; use python -m cqa.admin")
    store = Store(settings.db_path)
    security = SecurityStore(store, settings)
    if provider is None and settings.llm_api_key and settings.llm_model:
        provider = OpenAICompatibleProvider(
            settings.llm_base_url,
            settings.llm_api_key,
            settings.llm_model,
            settings.llm_timeout,
            max_output_tokens=settings.llm_max_output_tokens,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.initialize()
        initialize_appeals(store)
        store.save_checklist(default_checklist())
        security.initialize()
        yield

    app = FastAPI(
        title="CQA API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(SecurityMiddleware, security=security)
    app.include_router(auth_router(security))
    app.include_router(extension_router(store, settings))
    app.include_router(appeal_router(store))
    app.include_router(text_import_router(store, settings))
    app.include_router(submission_router(store))
    app.include_router(speaker_role_router(store, settings))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Pydantic's default response echoes input, which can include passwords/PII.
        return JSONResponse({"detail": "Invalid request data"}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        return JSONResponse(
            {"detail": "Internal error"},
            status_code=500,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @app.get("/healthz")
    def healthcheck():
        return {"status": "ok"}

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "evaluation_ready": provider is not None,
            "model": provider.model if provider else None,
        }

    @app.get("/api/checklists")
    def checklists():
        return store.list_checklists()

    @app.post("/api/checklists", status_code=201)
    def save_checklist(checklist: Checklist):
        try:
            key = store.save_checklist(checklist)
        except ChecklistConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"hash": key, "checklist": checklist}

    @app.post("/api/conversations/import", status_code=201)
    def import_conversations(dataset: DatasetEnvelope):
        conversations = [normalize_conversation(r) for r in dataset.data.records]
        keys = store.save_conversations(conversations)
        dataset_hash = store.save_dataset(dataset.data.dataset_group_id, conversations)
        return {
            "dataset_group_id": dataset.data.dataset_group_id,
            "count": len(keys),
            "conversation_hashes": keys,
            "dataset_hash": dataset_hash,
        }

    @app.post("/api/conversations", status_code=201)
    def add_conversation(source: ConversationInput):
        conversation = normalize_conversation(source)
        key = store.save_conversations([conversation])[0]
        return {"hash": key, "conversation": conversation.model_dump(exclude={"audio_url"})}

    @app.get("/api/conversations")
    def conversations(query: str = Query("", max_length=500)):
        return store.list_conversations(query)

    @app.get("/api/conversations/{key}")
    def get_conversation(key: str):
        conversation = store.conversation(key)
        if conversation is None:
            raise HTTPException(404, "Conversation not found")
        return {"hash": key, "conversation": conversation.model_dump(exclude={"audio_url"})}

    @app.post("/api/evaluations", status_code=201)
    async def evaluate_conversation(request: EvaluationRequest):
        conversation = store.conversation(request.conversation_hash)
        checklist = store.checklist(request.checklist_hash)
        if conversation is None or checklist is None:
            raise HTTPException(404, "Conversation or checklist not found")
        if provider is None:
            raise HTTPException(
                503, "Set LLM_API_KEY and LLM_MODEL on the backend to enable evaluation"
            )
        try:
            record = await evaluate_saved(store, provider, conversation, checklist)
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        except InvalidJudgments as exc:
            raise HTTPException(
                502,
                {
                    "message": "Model judgments failed validation; no score was saved",
                    "problems": exc.problems,
                },
            ) from exc
        return record

    @app.get("/api/evaluations/{key}")
    def get_evaluation(key: str):
        record = store.evaluation(key)
        if record is None:
            raise HTTPException(404, "Evaluation not found")
        return record

    if settings.frontend_dir:
        if not (settings.frontend_dir / "index.html").is_file():
            raise ValueError("Build the frontend before configuring CQA_FRONTEND_DIR")
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
    return app
