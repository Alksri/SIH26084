# Start the nowcasting system: http://localhost:8000
# Optional env: NOWCAST_MODE=simulated|live  NOWCAST_SPEED=10  NOWCAST_DROP_DIR=data/incoming
param([int]$Port = 8000)
if (-not (Test-Path .venv)) {
    python -m venv .venv
    .\.venv\Scripts\python -m pip install -r requirements.txt
}
.\.venv\Scripts\python -m uvicorn nowcast.server:app --app-dir backend --host 0.0.0.0 --port $Port
