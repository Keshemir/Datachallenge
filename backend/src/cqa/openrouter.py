"""Shared safe transport for STT and Decisions. No automatic paid retries."""

from math import isfinite

import httpx

from .provider import ProviderError


async def post_openrouter(
    path: str,
    key: str,
    *,
    payload: dict | None = None,
    data: dict | None = None,
    files: dict | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    base_url: str = "https://openrouter.ai",
) -> dict:
    try:
        async with httpx.AsyncClient(timeout=210, transport=transport) as client:
            response = await client.post(
                base_url.rstrip("/") + path,
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
                data=data,
                files=files,
            )
            response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("error"):
            raise ProviderError("OpenRouter returned an error; result was not accepted")
        return body
    except httpx.HTTPStatusError as exc:
        raise ProviderError(f"OpenRouter returned HTTP {exc.response.status_code}") from exc
    except httpx.TimeoutException as exc:
        raise ProviderError(
            "OpenRouter request timed out; billing may still have occurred"
        ) from exc
    except (httpx.RequestError, ValueError) as exc:
        raise ProviderError("OpenRouter request failed or returned invalid JSON") from exc


def reported_cost(body: dict) -> float | None:
    value = (body.get("usage") or {}).get("cost")
    return float(value) if type(value) in (float, int) and isfinite(value) and value >= 0 else None
