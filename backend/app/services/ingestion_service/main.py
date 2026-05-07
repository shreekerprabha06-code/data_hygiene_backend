import uvicorn

from app.routes.drafts import router as drafts_router
from app.core.database import close_db
from app.services.common import create_service_app, include_selected_routes


app = create_service_app("ingestion-service")

include_selected_routes(
    app,
    drafts_router,
    {
        ("POST", "/upload-execution-data"),
    },
)


@app.on_event("shutdown")
async def shutdown():
    close_db()


if __name__ == "__main__":
    uvicorn.run("app.services.ingestion_service.main:app", host="127.0.0.1", port=8004, reload=True)
