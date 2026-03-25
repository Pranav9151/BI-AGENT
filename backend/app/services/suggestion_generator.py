"""
Smart BI Agent — Dynamic Suggestion Generator
Phase 6.5 | IAM-Aware Query Suggestions

PURPOSE:
    Generate intelligent query suggestions based on the user's
    permission-filtered schema. Users only see suggestions for
    tables they have access to.

APPROACH:
    1. Load user's permission-filtered schema (same cache as query pipeline)
    2. Map table names to business categories using keyword matching
    3. Generate relevant questions based on column names within each table
    4. Return as structured categories with icon hints

SECURITY:
    - Uses the same 3-tier RBAC schema loading as the query pipeline
    - Users with restricted access see only categories matching their tables
    - Admin sees all categories for all accessible tables
"""
from __future__ import annotations

import re
from typing import Any

from app.logging.structured import get_logger

log = get_logger(__name__)


# =============================================================================
# Category Mapping — table name patterns → business categories
# =============================================================================

# (pattern, category_key, label, icon_hint, color_key)
_TABLE_CATEGORY_RULES: list[tuple[str, str, str, str, str]] = [
    (r"(?i)(revenue|sales|invoice|billing|payment|transaction)", "revenue", "Revenue & Sales", "trending-up", "emerald"),
    (r"(?i)(customer|client|account|contact|lead)", "customers", "Customers", "users", "blue"),
    (r"(?i)(employee|staff|hr|human.?resource|salary|payroll|department)", "hr", "Employees & HR", "building", "violet"),
    (r"(?i)(ticket|support|case|incident|helpdesk|complaint)", "support", "Support", "headphones", "amber"),
    (r"(?i)(campaign|marketing|lead|newsletter|funnel|conversion)", "marketing", "Marketing", "megaphone", "rose"),
    (r"(?i)(order|purchase|cart|checkout|shipment|fulfillment)", "orders", "Orders", "shopping-cart", "cyan"),
    (r"(?i)(product|item|catalog|inventory|sku|stock)", "products", "Products", "package", "indigo"),
    (r"(?i)(project|task|sprint|milestone|deliverable)", "projects", "Projects", "folder", "orange"),
    (r"(?i)(log|event|audit|activity|session)", "analytics", "Analytics & Logs", "activity", "slate"),
    (r"(?i)(region|location|branch|office|site|warehouse)", "locations", "Locations", "map-pin", "teal"),
]


# =============================================================================
# Question templates — column-aware question generation
# =============================================================================

def _generate_questions(table_name: str, columns: dict[str, Any]) -> list[str]:
    """Generate smart questions based on table name and column types."""
    questions: list[str] = []
    col_names = list(columns.keys())
    
    # Identify column types
    numeric_cols = [c for c, info in columns.items() if _is_numeric_type(info.get("type", ""))]
    date_cols = [c for c, info in columns.items() if _is_date_type(info.get("type", ""))]
    text_cols = [c for c, info in columns.items() if _is_text_type(info.get("type", "")) and not info.get("primary_key")]
    
    friendly_name = table_name.replace("_", " ").title()
    
    # Count query
    questions.append(f"How many records are in {friendly_name}?")
    
    # Group-by queries for text columns
    for col in text_cols[:2]:
        friendly_col = col.replace("_", " ")
        questions.append(f"Show {friendly_name} count by {friendly_col}")
    
    # Aggregation queries for numeric columns
    for col in numeric_cols[:2]:
        friendly_col = col.replace("_", " ")
        if any(kw in col.lower() for kw in ("amount", "total", "revenue", "price", "cost", "salary", "budget")):
            questions.append(f"What is the total {friendly_col} in {friendly_name}?")
        else:
            questions.append(f"Show average {friendly_col} in {friendly_name}")
    
    # Time-based queries
    for col in date_cols[:1]:
        friendly_col = col.replace("_", " ")
        questions.append(f"Show {friendly_name} trend by {friendly_col}")
    
    # Top N queries
    if numeric_cols and text_cols:
        questions.append(f"Show top 10 {friendly_name} by {numeric_cols[0].replace('_', ' ')}")
    
    return questions[:4]  # Cap at 4 per table


def _is_numeric_type(type_str: str) -> bool:
    t = type_str.lower()
    return any(kw in t for kw in ("int", "numeric", "decimal", "float", "double", "real", "money", "serial"))


def _is_date_type(type_str: str) -> bool:
    t = type_str.lower()
    return any(kw in t for kw in ("date", "time", "timestamp"))


def _is_text_type(type_str: str) -> bool:
    t = type_str.lower()
    return any(kw in t for kw in ("char", "text", "string", "varchar", "name"))


# =============================================================================
# Main Generator
# =============================================================================

def generate_suggestions(schema_data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Generate IAM-filtered suggestion categories from schema data.
    
    Args:
        schema_data: Permission-filtered schema dict
                     {table_name: {columns: {col_name: {type, nullable, primary_key}}}}
    
    Returns:
        List of category dicts:
        [
            {
                "key": "revenue",
                "label": "Revenue & Sales",
                "icon": "trending-up",
                "color": "emerald",
                "questions": ["What is total revenue?", ...]
            }
        ]
    """
    if not schema_data:
        return []
    
    # Map tables to categories
    categories: dict[str, dict[str, Any]] = {}
    
    for table_name, table_info in schema_data.items():
        columns = table_info.get("columns", {})
        if not columns:
            continue
        
        # Find matching category
        matched = False
        for pattern, cat_key, label, icon, color in _TABLE_CATEGORY_RULES:
            if re.search(pattern, table_name):
                if cat_key not in categories:
                    categories[cat_key] = {
                        "key": cat_key,
                        "label": label,
                        "icon": icon,
                        "color": color,
                        "questions": [],
                        "tables": [],
                    }
                categories[cat_key]["tables"].append(table_name)
                categories[cat_key]["questions"].extend(
                    _generate_questions(table_name, columns)
                )
                matched = True
                break
        
        # Unmatched tables go into a "General" category
        if not matched:
            if "general" not in categories:
                categories["general"] = {
                    "key": "general",
                    "label": "General",
                    "icon": "database",
                    "color": "slate",
                    "questions": [],
                    "tables": [],
                }
            categories["general"]["tables"].append(table_name)
            categories["general"]["questions"].extend(
                _generate_questions(table_name, columns)
            )
    
    # Deduplicate questions and cap per category
    result = []
    for cat in categories.values():
        seen = set()
        unique_questions = []
        for q in cat["questions"]:
            if q not in seen:
                seen.add(q)
                unique_questions.append(q)
        cat["questions"] = unique_questions[:4]
        del cat["tables"]  # Don't expose table list to frontend
        result.append(cat)
    
    # Sort: categories with more questions first
    result.sort(key=lambda c: len(c["questions"]), reverse=True)
    
    return result[:8]  # Max 8 categories