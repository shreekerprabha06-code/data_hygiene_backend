import asyncio

import uvicorn

from app.core.database import close_db
from app.services.pipeline import run_trigger
from app.services.common import add_websocket_endpoint, create_service_app


app = create_service_app("trigger-service")
add_websocket_endpoint(app)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "trigger-service"}


@app.on_event("startup")
async def startup():
    asyncio.create_task(run_trigger())


@app.on_event("shutdown")
async def shutdown():
    close_db()


if __name__ == "__main__":
    uvicorn.run("app.services.trigger_service.main:app", host="127.0.0.1", port=8005, reload=True)
