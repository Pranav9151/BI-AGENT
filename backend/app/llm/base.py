"""
Smart BI Agent — LLM Provider Base Interface
Architecture v3.1 | Layer 5 (AI Processing)

PURPOSE:
    Abstract base class for all LLM provider implementations.
    Build for multi-provider from day one — implement one at a time.

    Adding a new provider = one new file implementing BaseLLMProvider.

SECURITY:
    - API keys are passed in-memory only, never stored as instance state
    - System prompt contains NO security logic (all enforcement in code)
    - Token budgets tracked externally (not in provider)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LLMRequest:
    """Input to any LLM provider."""
    system_prompt: str
    user_message: str
    model: str
    max_tokens: int = 2048
    temperature: float = 0.1


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""
    content: str
    model: str
    provider_type: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    raw_response: Optional[dict] = field(default=None, repr=False)


class BaseLLMProvider(ABC):
    """
    Abstract base for all LLM providers.

    Implementations:
        - GroqProvider   (groq_provider.py) — Phase 4C
        - OpenAIProvider (openai_provider.py) — future
        - ClaudeProvider (claude_provider.py) — future
        - GeminiProvider (gemini_provider.py) — future
        - OllamaProvider (ollama_provider.py) — future

    Each provider translates LLMRequest into the provider-specific
    SDK call and returns a standardized LLMResponse.
    """

    provider_type: str = "base"

    @abstractmethod
    async def generate(
        self,
        request: LLMRequest,
        api_key: str,
        base_url: Optional[str] = None,
    ) -> LLMResponse:
        """
        Generate a completion from the LLM.

        Args:
            request: Standardized LLM request.
            api_key: Decrypted API key (in-memory only, never stored).
            base_url: Optional base URL override (Ollama).

        Returns:
            Standardized LLMResponse.

        Raises:
            LLMProviderError: On any provider failure.
        """
        ...

    @abstractmethod
    async def test_connectivity(
        self,
        api_key: str,
        model: str,
        base_url: Optional[str] = None,
    ) -> tuple[bool, Optional[int], Optional[str]]:
        """
        Quick connectivity test (lightweight prompt).

        Returns:
            (success, latency_ms, error_message)
        """
        ...
