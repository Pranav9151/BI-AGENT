"""
Smart BI Agent — LLM Provider Schemas
Architecture v3.1 | Layer 4 | Threats: T12 (API key exposure), T34 (Ollama SSRF)

Request and response schemas for the Multi-LLM BYOK provider system.

Security notes:
  - api_key present in CREATE/UPDATE requests ONLY — never in any response
  - Responses expose only a key_prefix (first 8 chars) for identification
  - encrypted_api_key (raw ciphertext) NEVER appears in any response schema
  - provider_type is an enum — prevents injection via type confusion
  - base_url (Ollama) is SSRF-validated at the route layer
  - is_default logic enforced in routes (only one default at a time)
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Enums
# =============================================================================

class ProviderType(str, Enum):
    """Supported LLM provider types."""
    openai   = "openai"
    claude   = "claude"
    gemini   = "gemini"
    groq     = "groq"
    deepseek = "deepseek"
    ollama   = "ollama"


class DataResidency(str, Enum):
    """Data residency region for compliance."""
    us      = "us"
    eu      = "eu"
    cn      = "cn"
    local   = "local"
    unknown = "unknown"


# =============================================================================
# Request Schemas
# =============================================================================

class LLMProviderCreateRequest(BaseModel):
    """
    POST /api/v1/llm-providers — body.

    api_key is accepted here and immediately encrypted with
    HKDF KeyPurpose.LLM_API_KEYS before storage (T12).
    It is NEVER returned in any response schema.

    For Ollama (provider_type="ollama"):
      - api_key may be omitted (self-hosted, no key needed)
      - base_url is required and SSRF-validated (T34)
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(
        ..., min_length=1, max_length=100,
        description="Human-readable label e.g. 'Company OpenAI Account'",
    )
    provider_type: ProviderType = Field(..., description="LLM provider engine")

    # Credentials — present in request, NEVER in response
    api_key: Optional[str] = Field(
        None, min_length=1, max_length=512,
        description="Provider API key. Required for all cloud providers. Null for Ollama.",
    )
    base_url: Optional[str] = Field(
        None, min_length=1, max_length=500,
        description="Base URL for Ollama (e.g. http://ollama:11434). SSRF-validated.",
    )

    # Model configuration
    model_sql: str = Field(
        ..., min_length=1, max_length=100,
        description="Model used for SQL generation (accuracy-critical, low temperature)",
    )
    model_insight: Optional[str] = Field(
        None, max_length=100,
        description="Model used for insight summarisation (can be lighter/cheaper)",
    )
    model_suggestion: Optional[str] = Field(
        None, max_length=100,
        description="Model used for question suggestions",
    )
    max_tokens_sql: int = Field(2048, ge=256, le=16384, description="Token budget for SQL generation")
    max_tokens_insight: int = Field(1024, ge=128, le=8192, description="Token budget for insight summaries")
    temperature_sql: float = Field(0.1, ge=0.0, le=1.0, description="Temperature for SQL generation (low = deterministic)")
    temperature_insight: float = Field(0.3, ge=0.0, le=1.0, description="Temperature for insight summaries")

    # Operational
    is_active: bool = Field(True, description="Whether this provider is enabled")
    is_default: bool = Field(False, description="Set as the default provider. Clears any existing default.")
    priority: int = Field(99, ge=1, le=999, description="Fallback chain priority: 1=primary, higher=lower priority")
    daily_token_budget: int = Field(1_000_000, ge=1000, description="Daily token budget ceiling (T36)")
    data_residency: DataResidency = Field(
        DataResidency.unknown,
        description="Data residency region for compliance (T19)",
    )


class LLMProviderUpdateRequest(BaseModel):
    """
    PATCH /api/v1/llm-providers/{id} — body.

    All fields optional. Omitting api_key preserves the existing encrypted key.
    Supplying api_key replaces and re-encrypts with the new value.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    api_key: Optional[str] = Field(None, min_length=1, max_length=512)
    base_url: Optional[str] = Field(None, min_length=1, max_length=500)
    model_sql: Optional[str] = Field(None, min_length=1, max_length=100)
    model_insight: Optional[str] = Field(None, max_length=100)
    model_suggestion: Optional[str] = Field(None, max_length=100)
    max_tokens_sql: Optional[int] = Field(None, ge=256, le=16384)
    max_tokens_insight: Optional[int] = Field(None, ge=128, le=8192)
    temperature_sql: Optional[float] = Field(None, ge=0.0, le=1.0)
    temperature_insight: Optional[float] = Field(None, ge=0.0, le=1.0)
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    priority: Optional[int] = Field(None, ge=1, le=999)
    daily_token_budget: Optional[int] = Field(None, ge=1000)
    data_residency: Optional[DataResidency] = None


# =============================================================================
# Response Schemas
# =============================================================================

class LLMProviderResponse(BaseModel):
    """
    Safe provider representation — NEVER includes the raw API key or ciphertext.

    key_prefix: first 8 characters of the plaintext key — enough for
    operators to identify which key is configured without exposing the full secret.
    Set to None for Ollama (no key).
    """
    model_config = ConfigDict(from_attributes=True)

    provider_id: str
    name: str
    provider_type: str
    key_prefix: Optional[str] = Field(
        None,
        description="First 8 chars of the API key for identification only (T12). None for Ollama.",
    )
    base_url: Optional[str]
    model_sql: str
    model_insight: Optional[str]
    model_suggestion: Optional[str]
    max_tokens_sql: int
    max_tokens_insight: int
    temperature_sql: float
    temperature_insight: float
    is_active: bool
    is_default: bool
    priority: int
    daily_token_budget: int
    data_residency: str
    created_by: Optional[str]


class LLMProviderListResponse(BaseModel):
    """Paginated list of LLM providers."""
    providers: list[LLMProviderResponse]
    total: int
    skip: int
    limit: int


class LLMProviderTestResponse(BaseModel):
    """
    POST /api/v1/llm-providers/{id}/test — response.

    Reports the result of a lightweight round-trip to the provider API.
    Error details are intentionally high-level — full error is logged server-side.
    """
    success: bool
    provider_type: str
    model_used: str
    latency_ms: Optional[int] = None
    error: Optional[str] = None


class LLMProviderSetDefaultResponse(BaseModel):
    """POST /api/v1/llm-providers/{id}/set-default — response."""
    provider_id: str
    name: str
    is_default: bool
    message: str


class ProviderModelEntry(BaseModel):
    """Single model entry in the models registry response."""
    model_id: str
    use_case: str   # "sql" | "insight" | "suggestion"
    is_default: bool


class ProviderModelsResponse(BaseModel):
    """GET /api/v1/llm-providers/models — static registry of known models per provider."""
    providers: dict[str, list[ProviderModelEntry]]