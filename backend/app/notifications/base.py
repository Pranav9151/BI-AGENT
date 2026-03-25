"""
Smart BI Agent — Base Notification Provider
Architecture v3.1 | Layer 8 | Threat: T6 (notification card injection)

Abstract interface for all notification providers.
All providers must escape content for their target format (T6).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class NotificationPayload:
    """Standard payload sent to all providers."""
    title: str
    body: str
    destination: str          # channel, email address, webhook URL, etc.
    format: str = "text"      # text | html | markdown
    attachments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NotificationResult:
    """Result of a notification delivery attempt."""
    success: bool
    provider_type: str
    destination: str
    message: str = ""
    error: Optional[str] = None


class BaseNotificationProvider(ABC):
    """Abstract base for notification providers."""

    provider_type: str = "base"

    @abstractmethod
    async def send(self, payload: NotificationPayload, config: dict[str, Any]) -> NotificationResult:
        """Send a notification. Config is the decrypted delivery_config."""
        ...

    @abstractmethod
    async def test_connectivity(self, config: dict[str, Any]) -> NotificationResult:
        """Test that the provider config is valid and reachable."""
        ...

    def _escape_text(self, text: str) -> str:
        """Default text escaping — strip HTML/script tags (T6)."""
        import re
        return re.sub(r'<[^>]+>', '', text)