import uvicorn

from app.routes.summary import router as summary_router
from app.routes.snapshots import router as snapshots_router
from app.core.database import close_db
from app.services.common import create_service_app, include_selected_routes


app = create_service_app("pipeline-service")

include_selected_routes(
    app,
    summary_router,
    {
        ("GET", "/invalid-summary"),
        ("GET", "/summary-poll"),
        ("GET", "/validation-counts"),
    },
)
include_selected_routes(
    app,
    snapshots_router,
    {
        ("GET", "/search-snapshots"),
    },
)


@app.on_event("shutdown")
async def shutdown():
    close_db()


if __name__ == "__main__":
    uvicorn.run("app.services.pipeline_service.main:app", host="127.0.0.1", port=8002, reload=True)
