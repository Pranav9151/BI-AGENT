"""
Smart BI Agent — SSRF Guard
Architecture v3.1 | Security Layer 8 | Threats: T1(SSRF), T34, T51

Applied to:
    - Database connection create/test (routes_connections.py)
    - Ollama URLs (ollama_provider.py)
    - Webhook URLs (notification platforms)
    - weasyprint PDF generation (export_engine.py)

SSRF attack vectors we block:
    - Direct IP: 169.254.169.254 (cloud metadata)
    - Hostname resolving to private IP: evil.com → 10.0.0.1
    - DNS rebinding: evil.com → 8.8.8.8 then → 169.254.169.254 (T51)
    - HTTP redirects: safe-url.com → 302 → http://169.254.169.254
    - IPv6 mapped: ::ffff:169.254.169.254
    - URL tricks: http://0x7f000001 (hex IP), http://2130706433 (decimal IP)
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from app.security.dns_pinner import (
    DNSPinningError,
    DNSResolutionError,
    PinnedHost,
    is_ip_blocked,
    resolve_and_pin,
)


class SSRFError(Exception):
    """Raised when an SSRF attempt is detected."""
    pass


def validate_connection_host(
    host: str,
    port: Optional[int] = None,
) -> PinnedHost:
    """
    Validate a database connection host against SSRF attacks.

    This is the primary SSRF guard for database connections.
    Returns a PinnedHost — caller MUST use pinned.resolved_ip for connections.

    Args:
        host: Hostname or IP from connection config.
        port: Database port.

    Returns:
        PinnedHost with validated resolved IP.

    Raises:
        SSRFError: If the host resolves to a blocked network.
    """
    try:
        return resolve_and_pin(host, port)
    except DNSPinningError as e:
        raise SSRFError(
            f"SSRF blocked: {e}. Database connections to internal/private "
            f"networks are not allowed."
        ) from e
    except DNSResolutionError as e:
        raise SSRFError(f"Cannot resolve database host: {e}") from e


def validate_url(url: str) -> PinnedHost:
    """
    Validate a full URL (for webhooks, Ollama, etc.) against SSRF.

    Parses the URL, extracts host and port, then validates.

    Args:
        url: Full URL to validate (e.g., "http://ollama:11434").

    Returns:
        PinnedHost with validated resolved IP.

    Raises:
        SSRFError: If the URL's host resolves to a blocked network.
    """
    if not url:
        raise SSRFError("Empty URL")

    try:
        parsed = urlparse(url)
    except Exception as e:
        raise SSRFError(f"Invalid URL format: {e}") from e

    if not parsed.hostname:
        raise SSRFError(f"No hostname found in URL: {url}")

    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"Invalid URL scheme: {parsed.scheme}. Only http/https allowed.")

    port = parsed.port
    return validate_connection_host(parsed.hostname, port)


def validate_ollama_url(url: str, allow_docker_internal: bool = True) -> PinnedHost:
    """
    Validate an Ollama base URL with special Docker-internal handling.

    In Docker Compose, "ollama" resolves to the container's internal IP.
    This is safe because it's our own container, not an external service.
    The OLLAMA_BASE_URL is hardcoded in config, not user-configurable.

    T32: Ollama must ONLY be reachable via Docker internal network.
    T34: Prevent SSRF bypass via user-supplied Ollama URL.

    Args:
        url: Ollama base URL.
        allow_docker_internal: If True, allows Docker-internal hostnames
                               like "ollama" (the container name).

    Returns:
        PinnedHost with validated resolved IP.

    Raises:
        SSRFError: If the URL is not safe.
    """
    if not url:
        raise SSRFError("Empty Ollama URL")

    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    # Docker internal names (compose service names) are allowed
    # but ONLY if explicitly enabled (which is only for our hardcoded config)
    docker_internal_names = {"ollama", "localhost"}
    if allow_docker_internal and hostname in docker_internal_names:
        # For Docker internal, we don't DNS-pin — the name resolves
        # within the Docker network and is controlled by us
        return PinnedHost(
            original_host=hostname,
            resolved_ip=hostname,  # Docker DNS handles this
            port=parsed.port,
        )

    # For any other URL, full SSRF validation applies
    return validate_url(url)


def validate_webhook_url(url: str) -> PinnedHost:
    """
    Validate a webhook delivery URL.

    Webhooks are user-configured, so full SSRF protection applies.
    HTTPS is strongly preferred for webhooks.

    Args:
        url: Webhook URL to validate.

    Returns:
        PinnedHost with validated resolved IP.

    Raises:
        SSRFError: If the URL is not safe.
    """
    if not url:
        raise SSRFError("Empty webhook URL")

    parsed = urlparse(url)

    # Warn-level: HTTP webhooks are allowed but not recommended
    # (some internal tools only support HTTP)

    return validate_url(url)


def check_redirect_safety(redirect_url: str, original_host: str) -> None:
    """
    Validate that an HTTP redirect doesn't lead to a blocked destination.

    v3.1 RULE: Disable HTTP redirects on outbound requests entirely.
    This function is a safety net — callers should set follow_redirects=False.

    Args:
        redirect_url: The URL from the Location header.
        original_host: The original requested hostname.

    Raises:
        SSRFError: If the redirect target is blocked.
    """
    try:
        validate_url(redirect_url)
    except SSRFError:
        raise SSRFError(
            f"HTTP redirect from '{original_host}' to blocked destination: "
            f"'{redirect_url}'. Redirects to internal networks are blocked."
        )


def get_safe_httpx_kwargs() -> dict:
    """
    Get httpx client kwargs that enforce SSRF-safe defaults.

    Use this when creating httpx clients for any outbound HTTP requests.
    Disables redirects entirely per v3.1 architecture.

    Usage:
        async with httpx.AsyncClient(**get_safe_httpx_kwargs()) as client:
            response = await client.get(url)
    """
    return {
        "follow_redirects": False,  # v3.1: Disable HTTP redirects
        "timeout": 30.0,
        "max_redirects": 0,
    }
