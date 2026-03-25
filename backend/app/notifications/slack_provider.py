"""
Smart BI Agent — Slack Notification Provider
Config: {"bot_token": "xoxb-...", "signing_secret": "..."}
"""
from __future__ import annotations

from typing import Any

from app.logging.structured import get_logger
from app.notifications.base import (
    BaseNotificationProvider, NotificationPayload, NotificationResult,
)

log = get_logger(__name__)


class SlackProvider(BaseNotificationProvider):
    provider_type = "slack"

    async def send(self, payload: NotificationPayload, config: dict[str, Any]) -> NotificationResult:
        try:
            from slack_sdk.web.async_client import AsyncWebClient
        except ImportError:
            return NotificationResult(
                success=False, provider_type=self.provider_type,
                destination=payload.destination,
                error="slack_sdk not installed. Install slack-bolt.",
            )

        try:
            client = AsyncWebClient(token=config["bot_token"])
            text = self._escape_text(payload.body)
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": self._escape_text(payload.title)[:150]}},
                {"type": "section", "text": {"type": "mrkdwn", "text": text[:3000]}},
            ]

            resp = await client.chat_postMessage(
                channel=payload.destination,
                text=text[:500],
                blocks=blocks,
            )

            log.info("slack.sent", channel=payload.destination, ok=resp.get("ok"))
            return NotificationResult(
                success=True, provider_type=self.provider_type,
                destination=payload.destination, message="Message sent to Slack",
            )
        except Exception as exc:
            log.error("slack.send_failed", error=str(exc))
            return NotificationResult(
                success=False, provider_type=self.provider_type,
                destination=payload.destination, error=str(exc)[:200],
            )

    async def test_connectivity(self, config: dict[str, Any]) -> NotificationResult:
        try:
            from slack_sdk.web.async_client import AsyncWebClient
        except ImportError:
            return NotificationResult(
                success=False, provider_type=self.provider_type,
                destination="", error="slack_sdk not installed",
            )

        try:
            client = AsyncWebClient(token=config["bot_token"])
            resp = await client.auth_test()
            bot_name = resp.get("bot_id", "unknown")
            return NotificationResult(
                success=True, provider_type=self.provider_type,
                destination="", message=f"Connected as bot {bot_name}",
            )
        except Exception as exc:
            return NotificationResult(
                success=False, provider_type=self.provider_type,
                destination="", error=str(exc)[:200],
            )