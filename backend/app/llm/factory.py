"""
Smart BI Agent — LLM Provider Factory
Architecture v3.1 | Layer 5 (AI Processing) | Threat: T45 (fallback chain)

PURPOSE:
    Resolves the correct LLM provider implementation based on provider_type.
    Loads provider config from the DB, decrypts the API key, and returns
    a ready-to-use provider instance.

    The fallback chain (T45) is ordered by priority:
        1 = primary, 2 = secondary, etc.
    If the primary fails, the next active provider is tried.

ADDING A NEW PROVIDER:
    1. Create backend/app/llm/{name}_provider.py implementing BaseLLMProvider
    2. Add to _PROVIDER_MAP below
    3. Done — the factory routes automatically
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors.exceptions import LLMProviderError
from app.llm.base import BaseLLMProvider, LLMRequest, LLMResponse
from app.llm.groq_provider import GroqProvider
from app.logging.structured import get_logger
from app.models.llm_provider import LLMProvider
from app.security.key_manager import KeyPurpose

log = get_logger(__name__)


# ─── Provider Registry ───────────────────────────────────────────────────────
# Add new providers here as they're built.

_PROVIDER_MAP: dict[str, type[BaseLLMProvider]] = {
    "groq": GroqProvider,
    # "openai": OpenAIProvider,     — future
    # "claude": ClaudeProvider,     — future
    # "gemini": GeminiProvider,     — future
    # "deepseek": DeepSeekProvider, — future
    # "ollama": OllamaProvider,     — future
}


def get_provider_instance(provider_type: str) -> BaseLLMProvider:
    """Get a provider implementation by type string."""
    cls = _PROVIDER_MAP.get(provider_type)
    if cls is None:
        raise LLMProviderError(
            message=f"Provider type '{provider_type}' is not yet supported.",
            detail=f"No implementation in _PROVIDER_MAP for: {provider_type}",
        )
    return cls()


async def get_active_providers(db: AsyncSession) -> list[LLMProvider]:
    """
    Load all active LLM providers ordered by fallback priority.
    Priority 1 = primary, 2 = secondary, etc.
    """
    result = await db.execute(
        select(LLMProvider)
        .where(LLMProvider.is_active == True)
        .order_by(LLMProvider.priority.asc())
    )
    return list(result.scalars().all())


async def get_default_provider(db: AsyncSession) -> Optional[LLMProvider]:
    """Get the default (is_default=True) active provider."""
    result = await db.execute(
        select(LLMProvider)
        .where(LLMProvider.is_active == True, LLMProvider.is_default == True)
    )
    return result.scalar_one_or_none()


async def generate_with_fallback(
    request: LLMRequest,
    db: AsyncSession,
    key_manager,
) -> LLMResponse:
    """
    Execute an LLM request with automatic fallback chain (T45).

    Strategy:
        1. Try default provider first (if set and active)
        2. On failure, iterate remaining active providers by priority
        3. If ALL fail, raise LLMProviderError with combined context

    Args:
        request: The LLM request to execute.
        db: Database session for loading provider configs.
        key_manager: HKDF key manager for decrypting API keys.

    Returns:
        LLMResponse from the first successful provider.

    Raises:
        LLMProviderError if no provider succeeds.
    """
    providers = await get_active_providers(db)

    if not providers:
        raise LLMProviderError(
            message="No active AI providers configured. Please add one in Settings.",
            detail="No active LLM providers in database",
        )

    # Sort: default first, then by priority
    providers.sort(key=lambda p: (not p.is_default, p.priority))

    errors: list[str] = []

    for provider_model in providers:
        # Check if we have an implementation for this type
        if provider_model.provider_type not in _PROVIDER_MAP:
            log.warning(
                "llm.factory.unsupported_type",
                provider=provider_model.name,
                type=provider_model.provider_type,
            )
            continue

        # Decrypt API key
        api_key: Optional[str] = None
        if provider_model.encrypted_api_key:
            try:
                api_key = key_manager.decrypt(
                    provider_model.encrypted_api_key,
                    KeyPurpose.LLM_API_KEYS,
                )
            except Exception as exc:
                log.error(
                    "llm.factory.key_decrypt_failed",
                    provider=provider_model.name,
                    error=str(exc),
                )
                errors.append(f"{provider_model.name}: key decryption failed")
                continue

        # Override model from provider config
        provider_request = LLMRequest(
            system_prompt=request.system_prompt,
            user_message=request.user_message,
            model=provider_model.model_sql,
            max_tokens=provider_model.max_tokens_sql,
            temperature=provider_model.temperature_sql,
        )

        instance = get_provider_instance(provider_model.provider_type)

        try:
            response = await instance.generate(
                request=provider_request,
                api_key=api_key or "",
                base_url=provider_model.base_url,
            )
            log.info(
                "llm.factory.success",
                provider=provider_model.name,
                type=provider_model.provider_type,
                model=provider_model.model_sql,
                latency_ms=response.latency_ms,
            )
            return response

        except LLMProviderError as exc:
            log.warning(
                "llm.factory.provider_failed",
                provider=provider_model.name,
                error=exc.detail if hasattr(exc, "detail") else str(exc),
            )
            errors.append(f"{provider_model.name}: {exc.message}")
            continue

    # All providers exhausted
    raise LLMProviderError(
        message="All AI providers failed. Please check your provider configuration.",
        detail=f"Fallback chain exhausted. Errors: {'; '.join(errors)}",
    )
