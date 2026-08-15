# Backend API image: Flask + LangChain, served by gunicorn.
FROM python:3.11-slim

WORKDIR /app

# Install dependencies first so this layer is cached when only source changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

# Container-level health check - `docker compose ps` shows healthy/unhealthy,
# and the deploy workflow waits on it.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:5000/health').status==200 else 1)"

# 2 workers, 120s timeout - Bedrock calls can take a while.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "app:app"]
