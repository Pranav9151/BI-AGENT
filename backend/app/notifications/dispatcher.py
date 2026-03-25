"""
Smart BI Agent — Notification Dispatcher
Architecture v3.1 | Factory pattern for routing to notification providers.

Supports: slack, email, teams, webhook
Future: whatsapp, jira, clickup
"""
from __future__ import annotations

import json
from typing import Any

from app.logging.structured import get_logger
from app.notifications.base import (
    BaseNotificationProvider,
    NotificationPayload,
    NotificationResult,
)

log = get_logger(__name__)

# Re-export for convenience
__all__ = ["dispatch_notification", "test_provider", "NotificationPayload", "NotificationResult"]


def _get_provider(platform_type: str) -> BaseNotificationProvider:
    """Factory: return the correct provider instance by platform_type."""
    if platform_type == "slack":
        from app.notifications.slack_provider import SlackProvider
        return SlackProvider()
    if platform_type == "email":
        from app.notifications.email_provider import EmailProvider
        return EmailProvider()
    if platform_type in ("teams", "webhook"):
        from app.notifications.teams_provider import TeamsProvider
        return TeamsProvider()

    raise ValueError(f"Unsupported notification platform: {platform_type}")


async def dispatch_notification(
    platform_type: str,
    config: dict[str, Any],
    payload: NotificationPayload,
) -> NotificationResult:
    """
    Send a notification via the correct provider.

    Args:
        platform_type: e.g. "slack", "email", "teams"
        config: Decrypted delivery_config dict
        payload: NotificationPayload with title, body, destination
    """
    try:
        provider = _get_provider(platform_type)
    except ValueError as exc:
        log.warning("dispatcher.unsupported", platform_type=platform_type)
        return NotificationResult(
            success=False,
            provider_type=platform_type,
            destination=payload.destination,
            error=str(exc),
        )

    log.info(
        "dispatcher.sending",
        provider=platform_type,
        destination=payload.destination,
    )

    result = await provider.send(payload, config)

    log.info(
        "dispatcher.result",
        provider=platform_type,
        success=result.success,
        destination=payload.destination,
    )

    return result


async def test_provider(
    platform_type: str,
    config: dict[str, Any],
) -> NotificationResult:
    """Test connectivity for a notification provider."""
    try:
        provider = _get_provider(platform_type)
    except ValueError as exc:
        return NotificationResult(
            success=False,
            provider_type=platform_type,
            destination="",
            error=str(exc),
        )

    return await provider.test_connectivity(config)