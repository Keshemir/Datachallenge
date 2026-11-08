import json
from dataclasses import dataclass
from math import isfinite
from typing import Protocol
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from .models import Model, ModelResponse


class ProviderError(RuntimeError):
    """Safe error text for clients; never include keys or upstream response bodies."""


@dataclass(frozen=True)
class ProviderReply:
    response: Model
    model: str
    request_id: str | None
    usage: dict[str, int]
    cost_usd: float | None = None


class JudgeProvider(Protocol):
    model: str

    async def judge(self, messages: list[dict[str, str]]) -> ProviderReply: ...


class OpenAICompatibleProvider:
    """Schema output, or native DeepSeek JSON mode with the same local validation."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 90,
        transport: httpx.AsyncBaseTransport | None = None,
        max_output_tokens: int = 6000,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.transport = transport
        self.max_output_tokens = max_output_tokens

    async def judge(self, messages: list[dict[str, str]]) -> ProviderReply:
        return await self.complete(messages, ModelResponse)

    async def complete(
        self, messages: list[dict[str, str]], response_model: type[Model]
    ) -> ProviderReply:
        schema = response_model.model_json_schema()
        payload = {
            "model": self.model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "conversation_judgments"
                    if response_model is ModelResponse
                    else response_model.__name__,
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        if urlparse(self.base_url).hostname == "openrouter.ai":
            payload["provider"] = {"require_parameters": True}
            payload["max_tokens"] = self.max_output_tokens
            if self.model.startswith("deepseek/"):
                # DeepSeek chat supports JSON mode; validate schema and evidence locally.
                # Preserve the account's routing/privacy restrictions.
                payload["provider"] = {
                    "order": ["fireworks", "together"],
                    "require_parameters": True,
                }
                payload["response_format"] = {"type": "json_object"}
                payload["messages"] = [
                    {
                        "role": "system",
                        "content": "Return a JSON object matching this schema: "
                        + json.dumps(schema),
                    },
                    *messages,
                ]
                payload["reasoning"] = {"effort": "low"}
        else:
            payload["max_completion_tokens"] = self.max_output_tokens
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                result = await client.post(
                    self.base_url + "/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                result.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderError("Model request timed out; no score was saved") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Model provider returned HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise ProviderError("Model provider is unavailable") from exc
        try:
            body = result.json()
            choice = body["choices"][0]
            message = choice["message"]
            if message.get("refusal"):
                raise ProviderError("Model refused the evaluation; no score was saved")
            if choice.get("finish_reason") != "stop":
                raise ProviderError("Model response is incomplete; no score was saved")
            parsed = response_model.model_validate_json(message["content"])
            model = body.get("model") or self.model
            if not isinstance(model, str):
                raise ValueError("Invalid model metadata")
            raw_usage = body.get("usage") or {}
            usage = {
                k: v
                for k, v in raw_usage.items()
                if k in ("prompt_tokens", "completion_tokens", "total_tokens")
                and type(v) is int
                and v >= 0
            }
            cost = raw_usage.get("cost")
            cost_usd = (
                float(cost) if type(cost) in (float, int) and isfinite(cost) and cost >= 0 else None
            )
            return ProviderReply(parsed, model, result.headers.get("x-request-id"), usage, cost_usd)
        except (
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            ValidationError,
            AttributeError,
        ) as exc:
            raise ProviderError(
                "Model returned invalid structured output; no score was saved"
            ) from exc
