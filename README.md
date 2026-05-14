# Backend Structure

The FastAPI microservices live under `app/`.

- `app/routes/` contains HTTP endpoint groups.
- `app/core/` contains infrastructure concerns such as database configuration.
- `app/schemas/` contains Pydantic request/response models.
- `app/services/` contains validation, standardization, websocket, and shared service logic.
- `scripts/` contains standalone maintenance scripts.

## Microservice Entrypoints

The architecture runs as separate service processes behind an NGINX API Gateway:

- **NGINX API Gateway** (Port 8000): Configured via `nginx.conf`
- `masterlist-service`: `python -m uvicorn app.services.masterlist_service.main:app --host 0.0.0.0 --port 8001 --reload`
- `pipeline-service`: `python -m uvicorn app.services.pipeline_service.main:app --host 0.0.0.0 --port 8002 --reload`
- `standardization-service`: `python -m uvicorn app.services.standardization_service.main:app --host 0.0.0.0 --port 8003 --reload`
- `ingestion-service`: `python -m uvicorn app.services.ingestion_service.main:app --host 0.0.0.0 --port 8004 --reload`
- `trigger-service`: `python -m uvicorn app.services.trigger_service.main:app --host 0.0.0.0 --port 8005 --reload` 

## How to run

On Windows, use the provided PowerShell script to launch NGINX and all five services at once:

```powershell
.\start_microservices.ps1 -Reload
```

*(You can also double-click `start_microservices.bat`)*
