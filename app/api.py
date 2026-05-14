"""
routes.py — Central Router Aggregator

This file collects all sub-routers from the modular route files
and exposes a single `router` object for main.py to include.

All endpoint logic has been split into:
  - app/routes/summary.py     → Dashboard & summary endpoints
  - app/routes/snapshots.py   → Snapshot detail & record lookup endpoints
  - app/routes/suggestions.py → Approve/reject suggestion endpoints
  - app/routes/drafts.py      → Draft record management & file upload endpoints

Shared helper functions live in:
  - app/helpers.py             → Reusable DB queries, broadcast, caching, etc.
"""
from fastapi import APIRouter

from app.routes.summary import router as summary_router
from app.routes.snapshots import router as snapshots_router
from app.routes.suggestions import router as suggestions_router
from app.routes.drafts import router as drafts_router

router = APIRouter()

# Include all sub-routers (no prefixes — preserves original URL paths exactly)
router.include_router(summary_router)
router.include_router(snapshots_router)
router.include_router(suggestions_router)
router.include_router(drafts_router)
