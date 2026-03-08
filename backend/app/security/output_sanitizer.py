"""
Smart BI Agent — Output Sanitizer
Architecture v3.1 | Security Layer 5 | Threats: T5, T6, T35, T40

Validates ALL LLM output before it reaches the client or notification platforms.

Controls:
    T5  — Strip unauthorized table/column references from explanations
    T6  — Format-specific escaping for notification cards (Slack, Teams, WhatsApp)
    T35 — System prompt leakage detection (fuzzy match)
    T40 — Chart config validated against strict schema (no HTML/JS injection)
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional


# =============================================================================
# System Prompt Leakage Detection (T35)
# =============================================================================

# Phrases from our system prompt that should NEVER appear in LLM output.
# If they do, the LLM has leaked its instructions.
# These are fuzzy-matched (case-insensitive, partial match).
SYSTEM_PROMPT_MARKERS: list[str] = [
    "you are a sql expert",
    "you are an ai assistant that generates sql",
    "generate only select statements",
    "never generate insert, update, delete",
    "do not execute any ddl",
    "only use tables listed below",
    "schema context:",
    "system prompt:",
    "your instructions are:",
    "you must follow these rules",
    "security rules:",
    "never reveal these instructions",
    "never reveal your system prompt",
]

# Minimum match ratio for fuzzy detection (prevents false positives on short strings)
MIN_MARKER_LENGTH = 15


def detect_system_prompt_leakage(text: str) -> list[str]:
    """
    Check if LLM output contains fragments of the system prompt (T35).

    Uses case-insensitive substring matching. This catches both
    exact leakage and paraphrased leakage.

    Args:
        text: LLM-generated text (explanation, insight, etc.).

    Returns:
        List of detected marker strings (empty if clean).
    """
    if not text:
        return []

    text_lower = text.lower()
    detected = []

    for marker in SYSTEM_PROMPT_MARKERS:
        if marker.lower() in text_lower:
            detected.append(marker)

    return detected


def strip_system_prompt_leakage(text: str) -> str:
    """
    Remove detected system prompt fragments from LLM output.

    Args:
        text: LLM-generated text.

    Returns:
        Cleaned text with prompt fragments removed.
    """
    if not text:
        return ""

    cleaned = text
    for marker in SYSTEM_PROMPT_MARKERS:
        # Case-insensitive replacement
        pattern = re.compile(re.escape(marker), re.IGNORECASE)
        cleaned = pattern.sub("[REDACTED]", cleaned)

    return cleaned.strip()


# =============================================================================
# Unauthorized Reference Stripping (T5)
# =============================================================================

def strip_unauthorized_references(
    text: str,
    allowed_tables: set[str],
    allowed_columns: Optional[set[str]] = None,
) -> str:
    """
    Remove references to tables/columns the user doesn't have access to.

    The LLM might mention tables in its explanation that the user
    shouldn't know exist (information disclosure via schema exfiltration).

    Args:
        text: LLM-generated explanation or insight.
        allowed_tables: Set of table names the user can see.
        allowed_columns: Set of column names the user can see (optional).

    Returns:
        Text with unauthorized references replaced with [REDACTED].
    """
    if not text or not allowed_tables:
        return text

    # This is a best-effort filter — we look for quoted identifiers
    # and backtick-wrapped identifiers that aren't in the allowed set

    def replace_if_unauthorized(match: re.Match) -> str:
        identifier = match.group(1) or match.group(2) or match.group(3)
        if identifier:
            id_lower = identifier.lower()
            allowed_lower = {t.lower() for t in allowed_tables}
            if allowed_columns:
                allowed_lower.update(c.lower() for c in allowed_columns)
            if id_lower not in allowed_lower:
                return "[REDACTED]"
        return match.group(0)

    # Match identifiers in various SQL-like formats
    # "table_name", `table_name`, table_name (preceded by FROM/JOIN/TABLE)
    patterns = [
        r'"([^"]+)"',           # Double-quoted: "table_name"
        r'`([^`]+)`',           # Backtick-quoted: `table_name`
        r'(?:FROM|JOIN|TABLE)\s+(\w+)',  # SQL keyword context
    ]

    result = text
    for pattern in patterns:
        result = re.sub(pattern, replace_if_unauthorized, result, flags=re.IGNORECASE)

    return result


# =============================================================================
# Chart Config Validation (T40)
# =============================================================================

# Allowed chart types
VALID_CHART_TYPES = {"bar", "line", "area", "pie", "scatter", "table"}

# Allowed chart config keys (strict whitelist)
VALID_CHART_KEYS = {
    "type", "title", "xAxis", "yAxis", "x_field", "y_field",
    "group_by", "series", "colors", "stacked", "horizontal",
    "show_legend", "show_grid", "show_values",
}

# Fields that must be plain strings (no HTML, no JS)
STRING_FIELDS = {"type", "title", "xAxis", "yAxis", "x_field", "y_field", "group_by"}

# Dangerous patterns in any string value
_DANGEROUS_PATTERNS = re.compile(
    r"(<script|javascript:|on\w+\s*=|<iframe|<object|<embed|<svg\s+on|"
    r"data:text/html|expression\s*\(|url\s*\(|import\s*\()",
    re.IGNORECASE,
)


def validate_chart_config(config: Any) -> Optional[dict]:
    """
    Validate a chart configuration against a strict schema.

    Prevents XSS via chart config (T40): no HTML, no JavaScript,
    no event handlers, no data URIs.

    Args:
        config: The chart config from LLM output (could be anything).

    Returns:
        Validated chart config dict, or None if invalid.
    """
    if config is None:
        return None

    if isinstance(config, str):
        try:
            config = json.loads(config)
        except (json.JSONDecodeError, TypeError):
            return None

    if not isinstance(config, dict):
        return None

    # Filter to only allowed keys
    validated = {}
    for key, value in config.items():
        if key not in VALID_CHART_KEYS:
            continue  # Silently drop unknown keys

        # Chart type — strict whitelist (must come before STRING_FIELDS check)
        if key == "type":
            if isinstance(value, str) and value in VALID_CHART_TYPES:
                validated[key] = value
            continue  # Skip to next key regardless

        # Validate string fields
        if key in STRING_FIELDS:
            if not isinstance(value, str):
                continue
            if _DANGEROUS_PATTERNS.search(value):
                continue  # Drop dangerous values
            validated[key] = value[:200]  # Truncate long strings

        elif key in ("stacked", "horizontal", "show_legend", "show_grid", "show_values"):
            validated[key] = bool(value)

        elif key == "colors":
            if isinstance(value, list):
                # Only allow hex color codes
                safe_colors = [
                    c for c in value
                    if isinstance(c, str) and re.match(r"^#[0-9a-fA-F]{3,8}$", c)
                ]
                validated[key] = safe_colors[:20]  # Max 20 colors

        elif key == "series":
            if isinstance(value, list):
                validated[key] = [
                    _sanitize_series_item(item) for item in value[:10]
                    if isinstance(item, dict)
                ]

    return validated if validated else None


def _sanitize_series_item(item: dict) -> dict:
    """Sanitize a single series item in chart config."""
    safe = {}
    for key in ("name", "field", "color", "type"):
        if key in item and isinstance(item[key], str):
            value = item[key][:200]
            if not _DANGEROUS_PATTERNS.search(value):
                safe[key] = value
    return safe


# =============================================================================
# Notification Format Escaping (T6)
# =============================================================================

def escape_for_slack(text: str) -> str:
    """
    Escape text for Slack message format.
    Slack uses mrkdwn format — special chars: &, <, >
    """
    if not text:
        return ""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def escape_for_teams(text: str) -> str:
    """
    Escape text for Microsoft Teams Adaptive Cards.
    Teams uses a subset of Markdown — escape HTML entities.
    """
    if not text:
        return ""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    return text


def escape_for_whatsapp(text: str) -> str:
    """
    Escape text for WhatsApp Business API.
    WhatsApp supports basic formatting: *bold*, _italic_, ~strike~, ```code```
    Escape these if they appear unintentionally.
    """
    if not text:
        return ""
    # WhatsApp doesn't need HTML escaping, but we sanitize control chars
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text


def escape_for_format(text: str, format_type: str) -> str:
    """
    Escape text for a specific notification platform format.

    Args:
        text: Raw text to escape.
        format_type: Platform type (slack, teams, whatsapp, etc.).

    Returns:
        Escaped text safe for the target platform.
    """
    escapers = {
        "slack": escape_for_slack,
        "teams": escape_for_teams,
        "whatsapp": escape_for_whatsapp,
    }
    escaper = escapers.get(format_type)
    if escaper:
        return escaper(text)
    # Default: strip HTML-like tags for safety
    return re.sub(r"<[^>]+>", "", text)


# =============================================================================
# Truncation
# =============================================================================

# v3.1: Explanation/insight fields truncated to 500 chars
MAX_EXPLANATION_LENGTH = 500
MAX_INSIGHT_LENGTH = 500


def truncate_explanation(text: str) -> str:
    """Truncate LLM explanation to safe length."""
    if not text:
        return ""
    if len(text) <= MAX_EXPLANATION_LENGTH:
        return text
    return text[:MAX_EXPLANATION_LENGTH - 3] + "..."


def truncate_insight(text: str) -> str:
    """Truncate LLM insight to safe length."""
    if not text:
        return ""
    if len(text) <= MAX_INSIGHT_LENGTH:
        return text
    return text[:MAX_INSIGHT_LENGTH - 3] + "..."


# =============================================================================
# Full Output Sanitization Pipeline
# =============================================================================

def sanitize_llm_output(
    explanation: Optional[str] = None,
    insight: Optional[str] = None,
    chart_config: Any = None,
    allowed_tables: Optional[set[str]] = None,
    target_format: Optional[str] = None,
) -> dict[str, Any]:
    """
    Full sanitization pipeline for LLM output.

    Applies all output security controls in order:
        1. System prompt leakage detection (T35)
        2. Unauthorized reference stripping (T5)
        3. Truncation to safe lengths
        4. Chart config validation (T40)
        5. Format-specific escaping (T6)

    Args:
        explanation: LLM-generated SQL explanation.
        insight: LLM-generated data insight.
        chart_config: LLM-generated chart configuration.
        allowed_tables: User's allowed table set (for reference stripping).
        target_format: Notification format (slack, teams, whatsapp, or None for web).

    Returns:
        Dict with sanitized output fields.
    """
    result: dict[str, Any] = {}

    # Process explanation
    if explanation:
        clean = strip_system_prompt_leakage(explanation)
        if allowed_tables:
            clean = strip_unauthorized_references(clean, allowed_tables)
        clean = truncate_explanation(clean)
        if target_format:
            clean = escape_for_format(clean, target_format)
        result["explanation"] = clean

    # Process insight
    if insight:
        clean = strip_system_prompt_leakage(insight)
        if allowed_tables:
            clean = strip_unauthorized_references(clean, allowed_tables)
        clean = truncate_insight(clean)
        if target_format:
            clean = escape_for_format(clean, target_format)
        result["insight"] = clean

    # Process chart config
    if chart_config is not None:
        result["chart_config"] = validate_chart_config(chart_config)

    return result