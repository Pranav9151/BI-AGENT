"""
Smart BI Agent — Email Notification Provider
Config: {"smtp_host": "...", "smtp_port": 587, "username": "...", "password": "...", "from_address": "..."}
"""
from __future__ import annotations

from typing import Any

from app.logging.structured import get_logger
from app.notifications.base import (
    BaseNotificationProvider, NotificationPayload, NotificationResult,
)

log = get_logger(__name__)


class EmailProvider(BaseNotificationProvider):
    provider_type = "email"

    async def send(self, payload: NotificationPayload, config: dict[str, Any]) -> NotificationResult:
        try:
            import aiosmtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
        except ImportError:
            return NotificationResult(
                success=False, provider_type=self.provider_type,
                destination=payload.destination,
                error="aiosmtplib not installed.",
            )

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = self._escape_text(payload.title)[:200]
            msg["From"] = config.get("from_address", config.get("username", "noreply@sbi.local"))
            msg["To"] = payload.destination

            body = self._escape_text(payload.body)
            msg.attach(MIMEText(body, "plain", "utf-8"))

            if payload.format == "html":
                msg.attach(MIMEText(payload.body, "html", "utf-8"))

            await aiosmtplib.send(
                msg,
                hostname=config["smtp_host"],
                port=config.get("smtp_port", 587),
                username=config.get("username"),
                password=config.get("password"),
                start_tls=True,
                timeout=15,
            )

            log.info("email.sent", to=payload.destination)
            return NotificationResult(
                success=True, provider_type=self.provider_type,
                destination=payload.destination, message="Email sent",
            )
        except Exception as exc:
            log.error("email.send_failed", error=str(exc))
            return NotificationResult(
                success=False, provider_type=self.provider_type,
                destination=payload.destination, error=str(exc)[:200],
            )

    async def test_connectivity(self, config: dict[str, Any]) -> NotificationResult:
        try:
            import aiosmtplib
        except ImportError:
            return NotificationResult(
                success=False, provider_type=self.provider_type,
                destination="", error="aiosmtplib not installed",
            )

        try:
            smtp = aiosmtplib.SMTP(
                hostname=config["smtp_host"],
                port=config.get("smtp_port", 587),
                start_tls=True,
                timeout=10,
            )
            await smtp.connect()
            if config.get("username") and config.get("password"):
                await smtp.login(config["username"], config["password"])
            await smtp.quit()

            return NotificationResult(
                success=True, provider_type=self.provider_type,
                destination="", message=f"SMTP connected to {config['smtp_host']}",
            )
        except Exception as exc:
            return NotificationResult(
                success=False, provider_type=self.provider_type,
                destination="", error=str(exc)[:200],
            )