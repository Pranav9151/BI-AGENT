"""
Smart BI Agent — LLM Provider Management Routes  (Component 12)
Architecture v3.1 | Layer 4 (Application) | Threats: T12 (key exposure),
                                                        T34 (Ollama SSRF),
                                                        T36 (token budget),
                                                        T19 (data residency)

ENDPOINTS:
    GET    /api/v1/llm-providers                     — list providers (admin)
    GET    /api/v1/llm-providers/models              — model registry (admin)
    GET    /api/v1/llm-providers/{id}                — get single provider (admin)
    POST   /api/v1/llm-providers                     — create provider (admin)
    PATCH  /api/v1/llm-providers/{id}                — update provider (admin)
    DELETE /api/v1/llm-providers/{id}                — soft-deactivate (admin)
    POST   /api/v1/llm-providers/{id}/test           — test connectivity (admin)
    POST   /api/v1/llm-providers/{id}/set-default    — promote to default (admin)

SECURITY:
    All endpoints are admin-only — LLM providers hold encrypted API keys
    that are rotated and billed against the customer's account.

API KEY HANDLING (T12):
    - Stored as HKDF-derived Fernet ciphertext (KeyPurpose.LLM_API_KEYS)
    - Only the first 8 characters (key_prefix) appear in any GET response
    - The plaintext key is used only transiently inside this process:
        create/update → encrypt → stored ciphertext
        test endpoint  → decrypt → instantiate provider → HTTP call → zero
    - The plaintext and full key are NEVER logged at any level

OLLAMA SSRF GUARD (T34):
    When provider_type == "ollama" and a base_url is supplied, the URL is
    validated via validate_url() before any DB write or HTTP call.
    SSRFError → 400 CONNECTION_BLOCKED (same shape as connection SSRF errors).

DEFAULT PROVIDER INVARIANT:
    The DB has a partial unique index allowing only one row where is_default=TRUE.
    The route layer proactively clears any existing default before setting a new
    one so the DB constraint is never violated. Clearing the old default and
    setting the new one happen inside a single transaction.

AUDIT:
    Every state-changing action (create, update, deactivate, set-default)
    writes to AuditWriter. The api_key is NEVER included in the audit question.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    CurrentUser,
    get_audit_writer,
    get_db,
    get_key_manager,
    require_admin,
)
from app.errors.exceptions import (
    DuplicateResourceError,
    ResourceNotFoundError,
    SSRFError,
    ValidationError,
)
from app.logging.structured import get_logger
from app.models.llm_provider import LLMProvider
from app.schemas.llm_provider import (
    DataResidency,
    LLMProviderCreateRequest,
    LLMProviderListResponse,
    LLMProviderResponse,
    LLMProviderSetDefaultResponse,
    LLMProviderTestResponse,
    LLMProviderUpdateRequest,
    ProviderModelEntry,
    ProviderModelsResponse,
    ProviderType,
)
from app.security.key_manager import KeyPurpose
from app.security.ssrf_guard import SSRFError as GuardSSRFError
from app.security.ssrf_guard import validate_url

log = get_logger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Static model registry  (Section 11 — PROVIDER_MODELS)
# ---------------------------------------------------------------------------

_PROVIDER_MODELS: dict[str, dict] = {
    "openai": {
        "sql":       ["gpt-4o", "gpt-4-turbo", "gpt-4o-mini"],
        "insight":   ["gpt-4o-mini", "gpt-3.5-turbo"],
        "default_sql":     "gpt-4o",
        "default_insight": "gpt-4o-mini",
    },
    "claude": {
        "sql":       ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
        "insight":   ["claude-haiku-4-5-20251001", "claude-sonnet-4-6"],
        "default_sql":     "claude-sonnet-4-6",
        "default_insight": "claude-haiku-4-5-20251001",
    },
    "gemini": {
        "sql":       ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
        "insight":   ["gemini-1.5-flash", "gemini-2.0-flash"],
        "default_sql":     "gemini-2.0-flash",
        "default_insight": "gemini-1.5-flash",
    },
    "groq": {
        "sql":       ["llama-3.3-70b-versatile", "mixtral-8x7b-32768"],
        "insight":   ["llama-3.1-8b-instant"],
        "default_sql":     "llama-3.3-70b-versatile",
        "default_insight": "llama-3.1-8b-instant",
    },
    "deepseek": {
        "sql":       ["deepseek-chat", "deepseek-reasoner"],
        "insight":   ["deepseek-chat"],
        "default_sql":     "deepseek-chat",
        "default_insight": "deepseek-chat",
    },
    "ollama": {
        "sql":       ["llama3.3:70b", "llama3.1:8b", "codellama:34b", "qwen2.5-coder:32b"],
        "insight":   ["llama3.2:3b", "llama3.1:8b"],
        "default_sql":     "llama3.3:70b",
        "default_insight": "llama3.2:3b",
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KEY_PREFIX_LENGTH = 8  # T12 — never show more than first 8 chars of API key


def _extract_key_prefix(key_manager, encrypted_api_key: Optional[str]) -> Optional[str]:
    """
    Decrypt the stored API key just far enough to extract the display prefix.

    Returns the first _KEY_PREFIX_LENGTH characters of the plaintext key,
    followed by '...' to signal truncation, or None if no key is stored.

    The plaintext string is never assigned to a long-lived variable (T12).
    """
    if not encrypted_api_key:
        return None
    try:
        plaintext = key_manager.decrypt(encrypted_api_key, KeyPurpose.LLM_API_KEYS)
        return plaintext[:_KEY_PREFIX_LENGTH] + "..." if len(plaintext) > _KEY_PREFIX_LENGTH else plaintext
    except Exception:
        # Decryption failure at read time → return sentinel rather than crash
        return "INVALID..."


def _provider_to_response(provider: LLMProvider, key_manager) -> LLMProviderResponse:
    """Convert an LLMProvider ORM object to a safe API response."""
    return LLMProviderResponse(
        provider_id=str(provider.id),
        name=provider.name,
        provider_type=provider.provider_type,
        key_prefix=_extract_key_prefix(key_manager, provider.encrypted_api_key),
        base_url=provider.base_url,
        model_sql=provider.model_sql,
        model_insight=provider.model_insight,
        model_suggestion=provider.model_suggestion,
        max_tokens_sql=provider.max_tokens_sql,
        max_tokens_insight=provider.max_tokens_insight,
        temperature_sql=provider.temperature_sql,
        temperature_insight=provider.temperature_insight,
        is_active=provider.is_active,
        is_default=provider.is_default,
        priority=provider.priority,
        daily_token_budget=provider.daily_token_budget,
        data_residency=provider.data_residency,
        created_by=str(provider.created_by) if provider.created_by else None,
    )


async def _get_provider_or_404(provider_id: uuid.UUID, db: AsyncSession) -> LLMProvider:
    """Fetch an LLMProvider by ID or raise ResourceNotFoundError (404)."""
    result = await db.execute(
        select(LLMProvider).where(LLMProvider.id == provider_id)
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        raise ResourceNotFoundError(
            message="LLM provider not found.",
            detail=f"LLMProvider {provider_id} does not exist",
        )
    return provider


def _get_client_ip(request: Request) -> str:
    """Extract client IP from X-Forwarded-For or direct connection."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _validate_cloud_key(provider_type: str, api_key: Optional[str]) -> None:
    """
    Enforce that cloud providers always have an API key.
    Ollama is exempt — self-hosted with no key.
    """
    if provider_type != ProviderType.ollama and not api_key:
        raise ValidationError(
            message="An API key is required for cloud LLM providers.",
            detail=f"provider_type={provider_type!r} requires api_key to be supplied",
        )


def _validate_ollama_url(provider_type: str, base_url: Optional[str]) -> None:
    """
    Enforce that Ollama providers supply a base_url, and SSRF-validate it.
    Raises SSRFError (400) if the URL resolves to a blocked network (T34).
    """
    if provider_type != ProviderType.ollama:
        return
    if not base_url:
        raise ValidationError(
            message="A base URL is required for Ollama providers.",
            detail="provider_type='ollama' requires base_url to be supplied",
        )
    try:
        validate_url(base_url)
    except GuardSSRFError as exc:
        raise SSRFError(
            message="Ollama base URL is not allowed.",
            detail=str(exc),
        ) from exc


async def _clear_existing_default(db: AsyncSession) -> None:
    """
    Atomically clear the is_default flag on all existing providers.
    Called inside a transaction just before setting the new default.
    """
    await db.execute(
        update(LLMProvider)
        .where(LLMProvider.is_default == True)  # noqa: E712
        .values(is_default=False)
    )


# =============================================================================
# GET /models  — Static model registry
# =============================================================================

@router.get(
    "/models",
    response_model=ProviderModelsResponse,
    summary="List available models per provider",
    description=(
        "Returns the static model registry — which models are available "
        "for each provider type, and which are the recommended defaults. "
        "Admin only."
    ),
)
async def list_models(
    admin: CurrentUser = Depends(require_admin),
) -> ProviderModelsResponse:
    """Return the static PROVIDER_MODELS registry as a structured response."""
    result: dict[str, list[ProviderModelEntry]] = {}

    for provider_type, info in _PROVIDER_MODELS.items():
        entries: list[ProviderModelEntry] = []
        default_sql = info.get("default_sql", "")
        default_insight = info.get("default_insight", "")

        for model_id in info.get("sql", []):
            entries.append(ProviderModelEntry(
                model_id=model_id,
                use_case="sql",
                is_default=(model_id == default_sql),
            ))
        for model_id in info.get("insight", []):
            entries.append(ProviderModelEntry(
                model_id=model_id,
                use_case="insight",
                is_default=(model_id == default_insight),
            ))
        result[provider_type] = entries

    log.info("llm_providers.models.listed", admin_id=admin["user_id"])
    return ProviderModelsResponse(providers=result)


# =============================================================================
# GET /  — List providers
# =============================================================================

@router.get(
    "/",
    response_model=LLMProviderListResponse,
    summary="List LLM providers",
    description="Returns a paginated list of all configured LLM providers. Admin only.",
)
async def list_providers(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    is_active: Optional[bool] = Query(None),
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    key_manager=Depends(get_key_manager),
) -> LLMProviderListResponse:
    """Paginated provider list with optional active-status filter."""
    conditions = []
    if is_active is not None:
        conditions.append(LLMProvider.is_active == is_active)

    count_stmt = select(func.count()).select_from(LLMProvider)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    data_stmt = (
        select(LLMProvider)
        .order_by(LLMProvider.priority.asc(), LLMProvider.created_at.asc())
        .offset(skip)
        .limit(limit)
    )
    if conditions:
        data_stmt = data_stmt.where(*conditions)
    providers = (await db.execute(data_stmt)).scalars().all()

    log.info("llm_providers.list", admin_id=admin["user_id"], total=total)

    return LLMProviderListResponse(
        providers=[_provider_to_response(p, key_manager) for p in providers],
        total=total,
        skip=skip,
        limit=limit,
    )


# =============================================================================
# GET /{provider_id}  — Get single provider
# =============================================================================

@router.get(
    "/{provider_id}",
    response_model=LLMProviderResponse,
    summary="Get LLM provider",
    description="Retrieve a single LLM provider by ID. Admin only.",
)
async def get_provider(
    provider_id: uuid.UUID,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    key_manager=Depends(get_key_manager),
) -> LLMProviderResponse:
    provider = await _get_provider_or_404(provider_id, db)
    log.info("llm_providers.get", admin_id=admin["user_id"], provider_id=str(provider_id))
    return _provider_to_response(provider, key_manager)


# =============================================================================
# POST /  — Create provider
# =============================================================================

@router.post(
    "/",
    response_model=LLMProviderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create LLM provider",
    description=(
        "Create a new LLM provider configuration. Admin only. "
        "The API key is encrypted at rest using HKDF KeyPurpose.LLM_API_KEYS. "
        "Only the first 8 characters are ever returned via the API (T12). "
        "For Ollama, the base_url is SSRF-validated before saving (T34)."
    ),
)
async def create_provider(
    request: Request,
    body: LLMProviderCreateRequest,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    key_manager=Depends(get_key_manager),
    audit=Depends(get_audit_writer),
) -> LLMProviderResponse:
    """
    Create an LLM provider configuration.

    Security pipeline:
        1. Validate cloud providers have an api_key
        2. SSRF guard for Ollama base_url (T34)
        3. Duplicate name check (case-sensitive)
        4. If is_default=True, clear any existing default in same transaction
        5. Encrypt api_key with HKDF LLM_API_KEYS — plaintext never stored
        6. Persist to DB
    """
    # Step 1: Cloud providers require a key
    _validate_cloud_key(body.provider_type, body.api_key)

    # Step 2: SSRF guard for Ollama
    _validate_ollama_url(body.provider_type, body.base_url)

    # Step 3: Duplicate name check
    dup = await db.execute(
        select(LLMProvider).where(LLMProvider.name == body.name)
    )
    if dup.scalar_one_or_none() is not None:
        raise DuplicateResourceError(
            message="An LLM provider with this name already exists.",
            detail=f"Duplicate LLM provider name: {body.name!r}",
        )

    # Step 4: Clear existing default if we're setting a new one
    if body.is_default:
        await _clear_existing_default(db)

    # Step 5: Encrypt API key — plaintext never stored (T12)
    encrypted_api_key: Optional[str] = None
    if body.api_key:
        encrypted_api_key = key_manager.encrypt(body.api_key, KeyPurpose.LLM_API_KEYS)

    # Step 6: Persist
    now = datetime.now(timezone.utc)
    new_provider = LLMProvider(
        id=uuid.uuid4(),
        name=body.name,
        provider_type=body.provider_type.value,
        encrypted_api_key=encrypted_api_key,
        base_url=body.base_url,
        model_sql=body.model_sql,
        model_insight=body.model_insight,
        model_suggestion=body.model_suggestion,
        max_tokens_sql=body.max_tokens_sql,
        max_tokens_insight=body.max_tokens_insight,
        temperature_sql=body.temperature_sql,
        temperature_insight=body.temperature_insight,
        is_active=body.is_active,
        is_default=body.is_default,
        priority=body.priority,
        daily_token_budget=body.daily_token_budget,
        data_residency=body.data_residency.value,
        created_by=uuid.UUID(admin["user_id"]),
    )
    new_provider.created_at = now
    new_provider.updated_at = now

    db.add(new_provider)
    await db.commit()

    log.info(
        "llm_providers.created",
        admin_id=admin["user_id"],
        provider_id=str(new_provider.id),
        provider_type=new_provider.provider_type,
        is_default=new_provider.is_default,
        # api_key intentionally ABSENT from log (T12)
    )

    if audit:
        await audit.log(
            execution_status="llm_provider.created",
            question=(
                f"Admin created LLM provider: {body.name!r} "
                f"(type={body.provider_type.value}, default={body.is_default})"
            ),
            user_id=admin["user_id"],
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return _provider_to_response(new_provider, key_manager)


# =============================================================================
# PATCH /{provider_id}  — Update provider
# =============================================================================

@router.patch(
    "/{provider_id}",
    response_model=LLMProviderResponse,
    summary="Update LLM provider",
    description=(
        "Partial-update an LLM provider. Admin only. "
        "Supplying api_key re-encrypts it; omitting it preserves the existing key. "
        "Setting is_default=True atomically demotes the previous default."
    ),
)
async def update_provider(
    provider_id: uuid.UUID,
    request: Request,
    body: LLMProviderUpdateRequest,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    key_manager=Depends(get_key_manager),
    audit=Depends(get_audit_writer),
) -> LLMProviderResponse:
    """Partial update an LLM provider configuration."""
    provider = await _get_provider_or_404(provider_id, db)
    changed_fields: list[str] = []

    # SSRF re-validate if base_url changes
    new_base_url = body.base_url if body.base_url is not None else provider.base_url
    if body.base_url is not None and provider.provider_type == ProviderType.ollama:
        try:
            validate_url(body.base_url)
        except GuardSSRFError as exc:
            raise SSRFError(
                message="Ollama base URL is not allowed.",
                detail=str(exc),
            ) from exc

    # Apply scalar fields
    if body.name is not None:
        provider.name = body.name
        changed_fields.append("name")
    if body.base_url is not None:
        provider.base_url = body.base_url
        changed_fields.append("base_url")
    if body.model_sql is not None:
        provider.model_sql = body.model_sql
        changed_fields.append("model_sql")
    if body.model_insight is not None:
        provider.model_insight = body.model_insight
        changed_fields.append("model_insight")
    if body.model_suggestion is not None:
        provider.model_suggestion = body.model_suggestion
        changed_fields.append("model_suggestion")
    if body.max_tokens_sql is not None:
        provider.max_tokens_sql = body.max_tokens_sql
        changed_fields.append("max_tokens_sql")
    if body.max_tokens_insight is not None:
        provider.max_tokens_insight = body.max_tokens_insight
        changed_fields.append("max_tokens_insight")
    if body.temperature_sql is not None:
        provider.temperature_sql = body.temperature_sql
        changed_fields.append("temperature_sql")
    if body.temperature_insight is not None:
        provider.temperature_insight = body.temperature_insight
        changed_fields.append("temperature_insight")
    if body.is_active is not None:
        provider.is_active = body.is_active
        changed_fields.append("is_active")
    if body.priority is not None:
        provider.priority = body.priority
        changed_fields.append("priority")
    if body.daily_token_budget is not None:
        provider.daily_token_budget = body.daily_token_budget
        changed_fields.append("daily_token_budget")
    if body.data_residency is not None:
        provider.data_residency = body.data_residency.value
        changed_fields.append("data_residency")

    # Re-encrypt API key if supplied (T12)
    if body.api_key is not None:
        provider.encrypted_api_key = key_manager.encrypt(
            body.api_key, KeyPurpose.LLM_API_KEYS
        )
        changed_fields.append("api_key")  # Note: field name only, never the value

    # Handle default promotion
    if body.is_default is True and not provider.is_default:
        await _clear_existing_default(db)
        provider.is_default = True
        changed_fields.append("is_default")
    elif body.is_default is False and provider.is_default:
        provider.is_default = False
        changed_fields.append("is_default")

    provider.updated_at = datetime.now(timezone.utc)
    await db.commit()

    log.info(
        "llm_providers.updated",
        admin_id=admin["user_id"],
        provider_id=str(provider_id),
        changed_fields=changed_fields,
        # api_key value intentionally ABSENT (T12)
    )

    if audit and changed_fields:
        await audit.log(
            execution_status="llm_provider.updated",
            question=(
                f"LLM provider {provider.name!r} ({provider_id}) "
                f"updated: {', '.join(changed_fields)}"
            ),
            user_id=admin["user_id"],
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return _provider_to_response(provider, key_manager)


# =============================================================================
# DELETE /{provider_id}  — Soft-deactivate
# =============================================================================

@router.delete(
    "/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate LLM provider",
    description=(
        "Soft-deactivate an LLM provider. Admin only. "
        "The record is never hard-deleted — it may appear in historical audit logs."
    ),
)
async def deactivate_provider(
    provider_id: uuid.UUID,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> Response:
    """Soft-deactivate by setting is_active=False. Also clears is_default."""
    provider = await _get_provider_or_404(provider_id, db)

    was_default = provider.is_default
    provider.is_active = False
    provider.is_default = False  # Can't be the default if deactivated
    provider.updated_at = datetime.now(timezone.utc)
    await db.commit()

    log.warning(
        "llm_providers.deactivated",
        admin_id=admin["user_id"],
        provider_id=str(provider_id),
        name=provider.name,
        was_default=was_default,
    )

    if audit:
        await audit.log(
            execution_status="llm_provider.deactivated",
            question=(
                f"Admin deactivated LLM provider: {provider.name!r} "
                f"({provider_id})"
                + (" — was the default provider" if was_default else "")
            ),
            user_id=admin["user_id"],
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# POST /{provider_id}/test  — Test provider connectivity
# =============================================================================

@router.post(
    "/{provider_id}/test",
    response_model=LLMProviderTestResponse,
    summary="Test LLM provider connectivity",
    description=(
        "Send a minimal round-trip request to the provider API to verify "
        "the key is valid and the chosen model is accessible. Admin only."
    ),
)
async def test_provider(
    provider_id: uuid.UUID,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    key_manager=Depends(get_key_manager),
) -> LLMProviderTestResponse:
    """
    Lightweight connectivity probe for an LLM provider.

    Process:
        1. Fetch provider from DB
        2. Decrypt API key in memory — never logged (T12)
        3. Attempt a minimal HTTP call to the provider API
        4. Return success/failure with latency

    The probe uses the model_sql configured for the provider, sending
    a minimal "Reply with OK" prompt to keep costs negligible.
    A failed probe does NOT deactivate the provider — it is purely
    informational for the admin.
    """
    provider = await _get_provider_or_404(provider_id, db)

    if not provider.is_active:
        return LLMProviderTestResponse(
            success=False,
            provider_type=provider.provider_type,
            model_used=provider.model_sql,
            error="Provider is deactivated.",
        )

    # Decrypt key for transient use only (T12)
    api_key: Optional[str] = None
    if provider.encrypted_api_key:
        try:
            api_key = key_manager.decrypt(provider.encrypted_api_key, KeyPurpose.LLM_API_KEYS)
        except Exception as exc:
            log.error(
                "llm_providers.test.decrypt_failed",
                provider_id=str(provider_id),
                error=str(exc),
            )
            return LLMProviderTestResponse(
                success=False,
                provider_type=provider.provider_type,
                model_used=provider.model_sql,
                error="API key could not be decrypted. The provider configuration may be corrupt.",
            )

    start_ms = int(time.monotonic() * 1000)
    success, error = await _run_provider_probe(
        provider_type=provider.provider_type,
        api_key=api_key,
        base_url=provider.base_url,
        model=provider.model_sql,
    )
    latency_ms = int(time.monotonic() * 1000) - start_ms

    # Zero the key reference immediately after the probe
    api_key = None  # noqa: F841 — explicit zero (T12)

    log.info(
        "llm_providers.tested",
        admin_id=admin["user_id"],
        provider_id=str(provider_id),
        provider_type=provider.provider_type,
        model=provider.model_sql,
        success=success,
        latency_ms=latency_ms,
        # error is logged, but never the key (T12)
    )

    return LLMProviderTestResponse(
        success=success,
        provider_type=provider.provider_type,
        model_used=provider.model_sql,
        latency_ms=latency_ms if success else None,
        error=error,
    )


async def _run_provider_probe(
    provider_type: str,
    api_key: Optional[str],
    base_url: Optional[str],
    model: str,
) -> tuple[bool, Optional[str]]:
    """
    Execute the minimal provider health-check probe.

    Isolated so it can be easily mocked in tests without affecting
    the route logic. Returns (success, error_message_or_None).

    This function imports provider adapters lazily — at this layer we
    don't need the full LLM stack unless a test is actually running.
    """
    import asyncio
    import httpx

    _PROBE_TIMEOUT = 15.0  # seconds

    try:
        if provider_type == "ollama":
            # Ollama: hit /api/tags to verify the daemon is up
            effective_url = (base_url or "http://ollama:11434").rstrip("/")
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
                resp = await client.get(f"{effective_url}/api/tags")
            if resp.status_code == 200:
                return True, None
            return False, f"Ollama returned HTTP {resp.status_code}."

        elif provider_type == "openai":
            import openai
            client = openai.AsyncOpenAI(api_key=api_key)
            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "Reply with OK"}],
                    max_tokens=5,
                    temperature=0,
                ),
                timeout=_PROBE_TIMEOUT,
            )
            return True, None

        elif provider_type == "claude":
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=api_key)
            await asyncio.wait_for(
                client.messages.create(
                    model=model,
                    max_tokens=5,
                    messages=[{"role": "user", "content": "Reply with OK"}],
                ),
                timeout=_PROBE_TIMEOUT,
            )
            return True, None

        elif provider_type == "gemini":
            # Gemini via REST — minimal token generation
            import json as _json
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={api_key}"
            )
            payload = {"contents": [{"parts": [{"text": "Reply with OK"}]}]}
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
                resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return True, None
            return False, f"Gemini returned HTTP {resp.status_code}."

        elif provider_type in ("groq", "deepseek"):
            # Both expose an OpenAI-compatible API
            base = "https://api.groq.com/openai/v1" if provider_type == "groq" \
                else "https://api.deepseek.com/v1"
            import openai
            client = openai.AsyncOpenAI(api_key=api_key, base_url=base)
            await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "Reply with OK"}],
                    max_tokens=5,
                    temperature=0,
                ),
                timeout=_PROBE_TIMEOUT,
            )
            return True, None

        else:
            return False, f"Unsupported provider type: {provider_type!r}."

    except asyncio.TimeoutError:
        return False, f"Request timed out after {int(_PROBE_TIMEOUT)}s."
    except ImportError as exc:
        # Provider SDK not installed — guide admin
        return False, f"Provider SDK not installed: {exc}."
    except Exception as exc:
        # Return a user-safe summary; full exception is logged at call-site (T12)
        return False, f"Provider error: {type(exc).__name__}."


# =============================================================================
# POST /{provider_id}/set-default  — Promote to default
# =============================================================================

@router.post(
    "/{provider_id}/set-default",
    response_model=LLMProviderSetDefaultResponse,
    summary="Set default LLM provider",
    description=(
        "Promote this provider to be the system default. "
        "Atomically demotes any previously-default provider. Admin only."
    ),
)
async def set_default_provider(
    provider_id: uuid.UUID,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> LLMProviderSetDefaultResponse:
    """
    Set this provider as the system default.

    The DB partial unique index (WHERE is_default = TRUE) ensures only one
    row is marked as default. We clear existing defaults before setting the
    new one — all within the same database transaction.
    """
    provider = await _get_provider_or_404(provider_id, db)

    if not provider.is_active:
        raise ValidationError(
            message="Cannot set a deactivated provider as default.",
            detail=f"LLMProvider {provider_id} is_active=False",
        )

    # Demote old default; promote new one (atomic in same transaction)
    await _clear_existing_default(db)
    provider.is_default = True
    provider.updated_at = datetime.now(timezone.utc)
    await db.commit()

    log.info(
        "llm_providers.set_default",
        admin_id=admin["user_id"],
        provider_id=str(provider_id),
        name=provider.name,
    )

    if audit:
        await audit.log(
            execution_status="llm_provider.set_default",
            question=f"Admin set LLM provider {provider.name!r} ({provider_id}) as default",
            user_id=admin["user_id"],
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return LLMProviderSetDefaultResponse(
        provider_id=str(provider.id),
        name=provider.name,
        is_default=True,
        message=f"'{provider.name}' is now the default LLM provider.",
    )