"""
Smart BI Agent — Security Headers Middleware
Architecture v3.1 | Layer 3 (API Gateway) | Threat: T21

PURPOSE:
    Inject security-critical HTTP response headers on EVERY response.
    These headers instruct the browser to enforce security policies
    that prevent XSS, clickjacking, MIME sniffing, and protocol downgrade.

HEADERS INJECTED:
    Strict-Transport-Security (HSTS):
        Forces HTTPS for 1 year including subdomains. Once a browser has
        seen this header it will NEVER connect over HTTP — even if the user
        types http://. max-age=31536000 is the recommended minimum.

    Content-Security-Policy (CSP):
        Controls which resources the browser is allowed to load.
        - default-src 'self': Only load from our own origin
        - script-src 'self': No inline scripts, no eval()
        - style-src 'self' 'unsafe-inline': Inline styles allowed (React needs this)
        - img-src 'self' data:: Allow data: URIs for QR codes (TOTP setup)
        - font-src 'self': No external fonts
        - connect-src 'self': API calls to self only (blocks exfiltration)
        - frame-ancestors 'none': Equivalent to X-Frame-Options DENY

    X-Frame-Options: DENY
        Belt-and-suspenders with frame-ancestors CSP. Older browsers
        that don't understand CSP still respect this header.

    X-Content-Type-Options: nosniff
        Prevents MIME-type sniffing. Browser must respect Content-Type.
        Prevents execution of content served with wrong MIME type.

    Referrer-Policy: strict-origin-when-cross-origin
        Sends full URL as referrer for same-origin requests.
        Sends only origin (no path) for cross-origin requests.
        This prevents leaking query parameters or route paths in referrer headers.

    Permissions-Policy:
        Disable browser features the app doesn't need.
        Reduces attack surface (e.g., no camera/microphone access).

    X-XSS-Protection: 0
        Intentionally disabling the browser's built-in XSS filter.
        The filter itself has known vulnerabilities in older browsers.
        CSP is the correct modern defence.

DEVELOPMENT vs PRODUCTION:
    HSTS is skipped in non-production to avoid bricking local HTTP dev servers.
    All other headers apply in all environments.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Injects security headers into every HTTP response.

    Order in middleware stack: Second (after RequestIDMiddleware).
    """

    def __init__(self, app, **kwargs) -> None:  # type: ignore[override]
        super().__init__(app, **kwargs)
        settings = get_settings()
        self._is_production = settings.is_production

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)
        self._inject_headers(response)
        return response

    def _inject_headers(self, response: Response) -> None:
        """Add all security headers to the response."""

        # HSTS — production only (don't break local HTTP dev)
        if self._is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        # Content Security Policy
        # Tightened for an API backend + SPA frontend combo
        csp_directives = [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",   # React inline styles
            "img-src 'self' data:",                 # data: for QR codes (TOTP)
            "font-src 'self'",
            "connect-src 'self'",
            "media-src 'none'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",              # Clickjacking prevention
            "upgrade-insecure-requests",
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_directives)

        # Clickjacking — belt-and-suspenders with frame-ancestors CSP
        response.headers["X-Frame-Options"] = "DENY"

        # MIME sniffing prevention
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Referrer — don't leak paths cross-origin
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions Policy — disable features we don't use
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), "
            "payment=(), usb=(), interest-cohort=()"
        )

        # Intentionally disable the broken browser XSS filter
        # CSP is the modern replacement
        response.headers["X-XSS-Protection"] = "0"

# Remove server identification — don't leak stack info
        if "server" in response.headers:
            del response.headers["server"]
        if "x-powered-by" in response.headers:
            del response.headers["x-powered-by"]
