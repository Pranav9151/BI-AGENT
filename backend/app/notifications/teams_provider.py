"""
Smart BI Agent — Microsoft Teams Notification Provider
Config: {"webhook_url": "https://..."}
"""
from __future__ import annotations

from typing import Any

from app.logging.structured import get_logger
from app.notifications.base import (
    BaseNotificationProvider, NotificationPayload, NotificationResult,
)

log = get_logger(__name__)


class TeamsProvider(BaseNotificationProvider):
    provider_type = "teams"

    async def send(self, payload: NotificationPayload, config: dict[str, Any]) -> NotificationResult:
        try:
            import httpx
        except ImportError:
            return NotificationResult(
                success=False, provider_type=self.provider_type,
                destination=payload.destination,
                error="httpx not installed.",
            )

        webhook_url = config.get("webhook_url", payload.destination)
        title = self._escape_text(payload.title)
        body = self._escape_text(payload.body)

        # Adaptive Card format for Teams
        card = {
            "type": "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium"},
                        {"type": "TextBlock", "text": body[:2000], "wrap": True},
                    ],
                },
            }],
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(webhook_url, json=card)
                resp.raise_for_status()

            log.info("teams.sent", destination=payload.destination)
            return NotificationResult(
                success=True, provider_type=self.provider_type,
                destination=payload.destination, message="Message sent to Teams",
            )
        except Exception as exc:
            log.error("teams.send_failed", error=str(exc))
            return NotificationResult(
                success=False, provider_type=self.provider_type,
                destination=payload.destination, error=str(exc)[:200],
            )

    async def test_connectivity(self, config: dict[str, Any]) -> NotificationResult:
        try:
            import httpx
        except ImportError:
            return NotificationResult(
                success=False, provider_type=self.provider_type,
                destination="", error="httpx not installed",
            )

        webhook_url = config.get("webhook_url", "")
        if not webhook_url:
            return NotificationResult(
                success=False, provider_type=self.provider_type,
                destination="", error="No webhook_url in config",
            )

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Send a minimal test card
                test_card = {
                    "type": "message",
                    "attachments": [{
                        "contentType": "application/vnd.microsoft.card.adaptive",
                        "content": {
                            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                            "type": "AdaptiveCard",
                            "version": "1.4",
                            "body": [{"type": "TextBlock", "text": "Smart BI Agent — Connection Test", "weight": "Bolder"}],
                        },
                    }],
                }
                resp = await client.post(webhook_url, json=test_card)
                resp.raise_for_status()

            return NotificationResult(
                success=True, provider_type=self.provider_type,
                destination="", message="Teams webhook reachable",
            )
        except Exception as exc:
            return NotificationResult(
                success=False, provider_type=self.provider_type,
                destination="", error=str(exc)[:200],
            )