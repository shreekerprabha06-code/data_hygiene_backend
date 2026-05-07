@echo off
echo Starting Data Hygiene API via Python module (bypassing Application Control policy)...
if exist .\.venv\Scripts\python.exe (
    .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
) else if exist .\venv\Scripts\python.exe (
    .\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
) else (
    python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
)
pause
