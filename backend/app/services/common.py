from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.services.ws_manager import manager


def create_service_app(title: str, version: str = "1.0.0") -> FastAPI:
    app = FastAPI(title=title, version=version)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


def include_selected_routes(app: FastAPI, source_router: APIRouter, route_keys: set[tuple[str, str]]) -> None:
    router = APIRouter()
    for route in source_router.routes:
        methods = getattr(route, "methods", set()) or set()
        path = getattr(route, "path", "")
        if any((method, path) in route_keys for method in methods):
            router.routes.append(route)
    app.include_router(router)


def add_websocket_endpoint(app: FastAPI) -> None:
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)
        except Exception:
            manager.disconnect(websocket)
