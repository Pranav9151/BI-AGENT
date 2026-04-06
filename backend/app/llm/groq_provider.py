"""
Smart BI Agent — Groq LLM Provider
Architecture v3.1 | Layer 5 (AI Processing)

Groq implementation of BaseLLMProvider.
Uses the groq Python SDK (pinned ==0.9.0 in pyproject.toml).

SECURITY:
    - API key passed per-call, never stored as instance attribute
    - Response content is raw text — all sanitization happens upstream
    - Errors are caught and wrapped in LLMProviderError (T10: no internal leak)
"""

from __future__ import annotations

import time
from typing import Optional

try:
    from groq import AsyncGroq, APIError, APIConnectionError, RateLimitError
    _GROQ_AVAILABLE = True
except Exception:  # pragma: no cover - exercised in environments without groq installed
    AsyncGroq = None  # type: ignore[assignment]
    APIError = Exception  # type: ignore[assignment]
    APIConnectionError = Exception  # type: ignore[assignment]
    RateLimitError = Exception  # type: ignore[assignment]
    _GROQ_AVAILABLE = False

from app.errors.exceptions import LLMProviderError
from app.llm.base import BaseLLMProvider, LLMRequest, LLMResponse
from app.logging.structured import get_logger

log = get_logger(__name__)


class GroqProvider(BaseLLMProvider):
    """Groq cloud LLM provider (Llama, Mixtral, etc.)."""

    provider_type = "groq"

    async def generate(
        self,
        request: LLMRequest,
        api_key: str,
        base_url: Optional[str] = None,
    ) -> LLMResponse:
        """
        Generate a completion via Groq API.

        The client is created per-call with the decrypted API key.
        This ensures the key is never held longer than necessary.
        """
        if not _GROQ_AVAILABLE:
            raise LLMProviderError(
                message="Groq provider is not available in this environment.",
                detail="Install the optional 'groq' dependency to enable this provider.",
            )
        client = AsyncGroq(api_key=api_key)
        start = time.monotonic()

        try:
            response = await client.chat.completions.create(
                model=request.model,
                messages=[
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.user_message},
                ],
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            )
        except RateLimitError as exc:
            log.warning("llm.groq.rate_limited", model=request.model, error=str(exc))
            raise LLMProviderError(
                message="AI provider rate limit reached. Please wait and try again.",
                detail=f"Groq rate limit: {exc}",
            ) from exc
        except APIConnectionError as exc:
            log.error("llm.groq.connection_error", model=request.model, error=str(exc))
            raise LLMProviderError(
                message="Could not connect to the AI provider.",
                detail=f"Groq connection error: {exc}",
            ) from exc
        except APIError as exc:
            log.error("llm.groq.api_error", model=request.model, status=getattr(exc, "status_code", None), error=str(exc))
            raise LLMProviderError(
                message="The AI service returned an error. Please try again.",
                detail=f"Groq API error: {exc}",
            ) from exc
        except Exception as exc:
            log.error("llm.groq.unexpected", model=request.model, error=str(exc))
            raise LLMProviderError(
                message="An unexpected error occurred with the AI service.",
                detail=f"Groq unexpected: {type(exc).__name__}: {exc}",
            ) from exc
        finally:
            await client.close()

        latency_ms = int((time.monotonic() - start) * 1000)

        content = response.choices[0].message.content or ""
        usage = response.usage

        log.info(
            "llm.groq.completed",
            model=request.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            latency_ms=latency_ms,
        )

        return LLMResponse(
            content=content,
            model=request.model,
            provider_type=self.provider_type,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            latency_ms=latency_ms,
        )

    async def test_connectivity(
        self,
        api_key: str,
        model: str,
        base_url: Optional[str] = None,
    ) -> tuple[bool, Optional[int], Optional[str]]:
        """Lightweight test: send a tiny prompt and measure round-trip."""
        if not _GROQ_AVAILABLE:
            return False, None, "Groq SDK is not installed."
        client = AsyncGroq(api_key=api_key)
        start = time.monotonic()

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Reply with OK"}],
                max_tokens=5,
                temperature=0,
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            return True, latency_ms, None
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            return False, latency_ms, str(exc)
        finally:
            await client.close()
