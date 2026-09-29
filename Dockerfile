FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir numpy scipy fastapi "uvicorn[standard]" pillow certifi google-genai h5py

COPY backend ./backend
COPY frontend ./frontend

# Hugging Face Spaces runs containers as a non-root user
RUN useradd -m -u 1000 app && mkdir -p /app/data/incoming && chown -R app /app
USER app

EXPOSE 8000
# $PORT is injected by Render / Railway / Cloud Run; HF Spaces uses 7860 (set PORT=7860 there)
CMD ["sh", "-c", "uvicorn nowcast.server:app --app-dir backend --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
