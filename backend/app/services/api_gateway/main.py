import asyncio
from typing import Optional

import httpx
import uvicorn
import websockets
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware


SERVICE_URLS = {
    "masterlist": "http://127.0.0.1:8001",
    "pipeline": "http://127.0.0.1:8002",
    "standardization": "http://127.0.0.1:8003",
    "ingestion": "http://127.0.0.1:8004",
    "trigger": "http://127.0.0.1:8005",
}

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}

app = FastAPI(title="api-gateway", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def resolve_service(method: str, path: str) -> Optional[str]:
    normalized_path = "/" + path.strip("/")

    if normalized_path in {"/unique-values", "/draft-records/fields"}:
        return SERVICE_URLS["masterlist"]
    if normalized_path.startswith("/metadata-values/"):
        return SERVICE_URLS["masterlist"]
    if method == "POST" and normalized_path.startswith("/draft-records/"):
        return SERVICE_URLS["masterlist"]

    if normalized_path in {"/invalid-summary", "/summary-poll", "/validation-counts", "/search-snapshots"}:
        return SERVICE_URLS["pipeline"]

    if normalized_path.startswith("/snapshot-records/"):
        return SERVICE_URLS["standardization"]
    if normalized_path in {"/approve-suggestion", "/reject-record"}:
        return SERVICE_URLS["standardization"]

    if normalized_path == "/upload-execution-data":
        return SERVICE_URLS["ingestion"]

    if normalized_path == "/health":
        return SERVICE_URLS["trigger"]

    return None


def filtered_headers(headers) -> dict:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_http(path: str, request: Request):
    service_url = resolve_service(request.method, path)
    if not service_url:
        return Response(
            content=f"No gateway route for {request.method} /{path}",
            status_code=404,
            media_type="text/plain",
        )

    target_url = httpx.URL(f"{service_url}/{path}").copy_with(query=request.url.query.encode("utf-8"))
    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            upstream = await client.request(
                request.method,
                target_url,
                content=body,
                headers=filtered_headers(request.headers),
            )
    except httpx.ConnectError:
        return Response(
            content=f"Downstream service unavailable for {request.method} /{path}: {service_url}",
            status_code=503,
            media_type="text/plain",
        )

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=filtered_headers(upstream.headers),
        media_type=upstream.headers.get("content-type"),
    )


@app.websocket("/ws")
async def proxy_websocket(websocket: WebSocket):
    await websocket.accept()
    upstream_url = "ws://127.0.0.1:8005/ws"

    try:
        async with websockets.connect(upstream_url) as upstream:
            async def browser_to_service():
                while True:
                    message = await websocket.receive_text()
                    await upstream.send(message)

            async def service_to_browser():
                while True:
                    message = await upstream.recv()
                    await websocket.send_text(message)

            await asyncio.gather(browser_to_service(), service_to_browser())
    except WebSocketDisconnect:
        return
    except Exception:
        await websocket.close()


if __name__ == "__main__":
    uvicorn.run("app.services.api_gateway.main:app", host="127.0.0.1", port=8000, reload=True)
