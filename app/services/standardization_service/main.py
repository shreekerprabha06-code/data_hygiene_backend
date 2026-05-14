import uvicorn

from app.routes.snapshots import router as snapshots_router
from app.routes.suggestions import router as suggestions_router
from app.core.database import close_db
from app.services.common import add_websocket_endpoint, create_service_app, include_selected_routes


app = create_service_app("standardization-service")

include_selected_routes(
    app,
    snapshots_router,
    {
        ("GET", "/snapshot-records/{Execution_id}"),
        ("GET", "/snapshot-records/{Execution_id}/"),
        ("POST", "/snapshot-records/{Execution_id}/assign"),
    },
)
include_selected_routes(
    app,
    suggestions_router,
    {
        ("PUT", "/approve-suggestion"),
        ("PUT", "/reject-record"),
        ("POST", "/reassign-records"),
        ("GET", "/eligible-users"),
        ("GET", "/eligible-users/"),
    },
)
add_websocket_endpoint(app)


import asyncio
from app.services.validation import get_validator

@app.on_event("startup")
async def startup():
    print("Pre-loading AI Validator Model in background...")
    asyncio.create_task(get_validator())

@app.on_event("shutdown")
async def shutdown():
    close_db()


if __name__ == "__main__":
    uvicorn.run("app.services.standardization_service.main:app", host="127.0.0.1", port=8003, reload=True)
