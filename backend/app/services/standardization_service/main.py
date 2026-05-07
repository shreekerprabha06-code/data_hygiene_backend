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
    },
)
include_selected_routes(
    app,
    suggestions_router,
    {
        ("PUT", "/approve-suggestion"),
        ("PUT", "/reject-record"),
    },
)
add_websocket_endpoint(app)


from app.services.validation import get_validator

@app.on_event("startup")
async def startup():
    print("Pre-loading AI Validator Model...")
    await get_validator()
    print("Validator Model Loaded.")

@app.on_event("shutdown")
async def shutdown():
    close_db()


if __name__ == "__main__":
    uvicorn.run("app.services.standardization_service.main:app", host="127.0.0.1", port=8003, reload=True)
