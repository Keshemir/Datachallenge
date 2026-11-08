import time
from datetime import UTC, datetime
from uuid import uuid4

from .engine import evaluate
from .inputs import fingerprint
from .models import Checklist, Conversation
from .prompt import PROMPT_VERSION, build_messages, response_schema
from .provider import JudgeProvider


async def run_evaluation(
    conversation: Conversation, checklist: Checklist, provider: JudgeProvider
) -> dict:
    messages = build_messages(conversation, checklist)
    started = time.perf_counter()
    reply = await provider.judge(messages)
    result = evaluate(conversation, checklist, reply.response)
    return {
        "id": str(uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "conversation_hash": fingerprint(conversation),
        "checklist_hash": fingerprint(checklist),
        "prompt_version": PROMPT_VERSION,
        "request_hash": fingerprint(
            {"messages": messages, "schema": response_schema(), "requested_model": provider.model}
        ),
        "model": reply.model,
        "provider_request_id": reply.request_id,
        "usage": reply.usage,
        "cost_usd": reply.cost_usd,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "result": result.model_dump(mode="json"),
    }
