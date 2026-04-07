"""
Smart BI Agent — Prometheus Metrics
Architecture v3.1 | Layer 3 (Observability)

PURPOSE:
    Expose /metrics endpoint for Prometheus scraping.
    Tracks HTTP request counts, latencies, and business-specific gauges.

METRICS EXPORTED:
    sbi_http_requests_total{method, path_group, status}   — Counter
    sbi_http_request_duration_seconds{method, path_group}  — Histogram
    sbi_llm_requests_total{provider, status}               — Counter
    sbi_llm_request_duration_seconds{provider}             — Histogram
    sbi_active_connections                                  — Gauge
    sbi_circuit_breaker_state{provider}                     — Gauge (0=closed, 1=open)

USAGE:
    from app.metrics import track_llm_request, track_llm_failure
    track_llm_request(provider="groq", duration_s=0.42)
"""

from __future__ import annotations

import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from app.logging.structured import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# In-process metrics store (no external dependency required).
# For production at scale, swap with prometheus_client if desired.
# ---------------------------------------------------------------------------

_counters: dict[str, int] = {}
_histograms: dict[str, list[float]] = {}
_gauges: dict[str, float] = {}


def _inc(name: str, labels: dict[str, str], value: int = 1) -> None:
    key = f"{name}{{{','.join(f'{k}={v!r}' for k, v in sorted(labels.items()))}}}"
    _counters[key] = _counters.get(key, 0) + value


def _observe(name: str, labels: dict[str, str], value: float) -> None:
    key = f"{name}{{{','.join(f'{k}={v!r}' for k, v in sorted(labels.items()))}}}"
    _histograms.setdefault(key, []).append(value)
    # Keep only last 10000 observations to bound memory
    if len(_histograms[key]) > 10000:
        _histograms[key] = _histograms[key][-5000:]


def _set_gauge(name: str, labels: dict[str, str], value: float) -> None:
    key = f"{name}{{{','.join(f'{k}={v!r}' for k, v in sorted(labels.items()))}}}"
    _gauges[key] = value


# ---------------------------------------------------------------------------
# Public API for business metrics
# ---------------------------------------------------------------------------

def track_llm_request(provider: str, duration_s: float) -> None:
    _inc("sbi_llm_requests_total", {"provider": provider, "status": "success"})
    _observe("sbi_llm_request_duration_seconds", {"provider": provider}, duration_s)


def track_llm_failure(provider: str) -> None:
    _inc("sbi_llm_requests_total", {"provider": provider, "status": "failure"})


def set_circuit_breaker_state(provider: str, is_open: bool) -> None:
    _set_gauge("sbi_circuit_breaker_state", {"provider": provider}, 1.0 if is_open else 0.0)


# ---------------------------------------------------------------------------
# Path grouping — collapse IDs to keep cardinality bounded
# ---------------------------------------------------------------------------

def _group_path(path: str) -> str:
    """Collapse UUID/ID segments to keep metric cardinality manageable."""
    parts = path.rstrip("/").split("/")
    grouped = []
    for p in parts:
        # Replace UUID-like or numeric segments with placeholder
        if len(p) >= 32 or (p.isdigit() and len(p) > 2):
            grouped.append(":id")
        else:
            grouped.append(p)
    return "/".join(grouped) or "/"


# ---------------------------------------------------------------------------
# HTTP metrics middleware
# ---------------------------------------------------------------------------

class MetricsMiddleware(BaseHTTPMiddleware):
    """Track HTTP request count and duration per path group."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip metrics endpoint itself
        if request.url.path == "/metrics":
            return await call_next(request)

        start = time.monotonic()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            duration = time.monotonic() - start
            method = request.method
            path_group = _group_path(request.url.path)
            status = str(response.status_code if response else 500)

            _inc("sbi_http_requests_total", {"method": method, "path_group": path_group, "status": status})
            _observe("sbi_http_request_duration_seconds", {"method": method, "path_group": path_group}, duration)


# ---------------------------------------------------------------------------
# /metrics endpoint — Prometheus text exposition format
# ---------------------------------------------------------------------------

def metrics_response() -> PlainTextResponse:
    """Render all metrics in Prometheus text exposition format."""
    lines: list[str] = []

    # Counters
    for key, value in sorted(_counters.items()):
        lines.append(f"{key} {value}")

    # Histograms — emit count, sum, and selected quantiles
    for key, values in sorted(_histograms.items()):
        if not values:
            continue
        name = key.split("{")[0]
        labels = key[len(name):]
        count = len(values)
        total = sum(values)
        sorted_vals = sorted(values)

        lines.append(f"{name}_count{labels} {count}")
        lines.append(f"{name}_sum{labels} {total:.6f}")

        for q, label in [(0.5, "0.5"), (0.9, "0.9"), (0.95, "0.95"), (0.99, "0.99")]:
            idx = min(int(count * q), count - 1)
            lines.append(f'{name}{{quantile="{label}",{labels[1:]} {sorted_vals[idx]:.6f}')

    # Gauges
    for key, value in sorted(_gauges.items()):
        lines.append(f"{key} {value}")

    body = "\n".join(lines) + "\n"
    return PlainTextResponse(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")
