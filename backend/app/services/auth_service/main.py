import uvicorn
from app.services.common import create_service_app, include_selected_routes
from app.routes.auth import router as auth_router

app = create_service_app("auth-service")

# Note: The auth service handles /login and /verify
include_selected_routes(
    app,
    auth_router,
    {
        ("POST", "/login"),
        ("GET", "/verify"),
        ("POST", "/register")
    },
)

if __name__ == "__main__":
    uvicorn.run("app.services.auth_service.main:app", host="127.0.0.1", port=8006, reload=True)
