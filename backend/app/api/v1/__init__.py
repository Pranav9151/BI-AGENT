"""
Smart BI Agent — API v1 Router
Architecture v3.1 | Layer 4

Central router that aggregates all v1 endpoint routers.
As Phase 2 routes are built, they are imported and included here.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1")

# Phase 2 routes are included here as they're built:
from app.api.v1.routes_auth import router as auth_router
from app.api.v1.routes_users import router as users_router
from app.api.v1.routes_connections import router as connections_router
from app.api.v1.routes_query import router as query_router
from app.api.v1.routes_schema import router as schema_router
from app.api.v1.routes_llm_providers import router as llm_router
from app.api.v1.routes_saved_queries import router as saved_queries_router
from app.api.v1.routes_conversations import router as conversations_router
from app.api.v1.routes_schedules import router as schedules_router
from app.api.v1.routes_notifications import router as notifications_router
from app.api.v1.routes_permissions import router as permissions_router
from app.api.v1.routes_export import router as export_router
from app.api.v1.routes_integrations import router as integrations_router

router.include_router(auth_router,          prefix="/auth",           tags=["auth"])
router.include_router(users_router,         prefix="/users",          tags=["users"])
router.include_router(connections_router,   prefix="/connections",    tags=["connections"])
router.include_router(query_router,         prefix="/query",          tags=["query"])
router.include_router(schema_router,        prefix="/schema",         tags=["schema"])
router.include_router(llm_router,           prefix="/llm-providers",  tags=["llm-providers"])
router.include_router(saved_queries_router, prefix="/saved-queries",  tags=["saved-queries"])
router.include_router(conversations_router, prefix="/conversations",  tags=["conversations"])
router.include_router(schedules_router,     prefix="/schedules",      tags=["schedules"])
router.include_router(notifications_router, prefix="/notifications",  tags=["notifications"])
router.include_router(permissions_router,   prefix="/permissions",    tags=["permissions"])
router.include_router(export_router,        prefix="/export",         tags=["export"])
router.include_router(integrations_router,  prefix="/integrations",   tags=["integrations"])