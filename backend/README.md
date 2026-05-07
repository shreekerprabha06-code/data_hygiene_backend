# Backend Structure

The FastAPI application now lives under `app/`.

- `app/main.py` creates the FastAPI app, websocket endpoint, startup hooks, and shutdown hooks.
- `app/api.py` aggregates route modules.
- `app/routes/` contains HTTP endpoint groups.
- `app/core/` contains infrastructure concerns such as database configuration.
- `app/schemas/` contains Pydantic request/response models.
- `app/services/` contains validation, standardization, websocket, and shared service logic.
- `app/utils.py` contains small document helpers.
- `scripts/` contains standalone maintenance scripts.

Root-level modules such as `main.py`, `database.py`, and `validation.py` are compatibility wrappers for older commands and imports.

## Microservice Entrypoints

The modular monolith can also be run as separate service processes:

- `api-gateway`: `python -m uvicorn app.services.api_gateway.main:app --host 0.0.0.0 --port 8000 --reload`
- `masterlist-service`: `python -m uvicorn app.services.masterlist_service.main:app --host 0.0.0.0 --port 8001 --reload`
- `pipeline-service`: `python -m uvicorn app.services.pipeline_service.main:app --host 0.0.0.0 --port 8002 --reload`
- `standardization-service`: `python -m uvicorn app.services.standardization_service.main:app --host 0.0.0.0 --port 8003 --reload`
- `ingestion-service`: `python -m uvicorn app.services.ingestion_service.main:app --host 0.0.0.0 --port 8004 --reload`
- `trigger-service`: `python -m uvicorn app.services.trigger_service.main:app --host 0.0.0.0 --port 8005 --reload`

The trigger worker can also be run without an HTTP port using `python -m app.services.trigger_service.worker`.

On Windows, `start_microservices.bat` launches the gateway and all five services.
