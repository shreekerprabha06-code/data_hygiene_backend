import uvicorn
from app.routes.drafts import router as drafts_router
from app.routes.snapshots import router as snapshots_router
from app.core.database import close_db
from app.services.common import create_service_app, include_selected_routes


app = create_service_app("masterlist-service")

include_selected_routes(
    app,
    snapshots_router,
    {
        ("GET", "/unique-values"),
        ("GET", "/metadata-values/{type_name}/{value}"),
    },
)
include_selected_routes(
    app,
    drafts_router,
    {
        ("GET", "/draft-records/fields"),
        ("POST", "/draft-records/{type_name}"),
    },
)


@app.on_event("shutdown")
async def shutdown():
    close_db()


if __name__ == "__main__":
    uvicorn.run("app.services.masterlist_service.main:app", host="127.0.0.1", port=8001, reload=True)
