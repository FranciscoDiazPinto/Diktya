# Imagen única para la API y el worker de cambios. No contiene secretos ni el frontend.
FROM python:3.15-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Cuenta sin privilegios: el proceso expuesto no corre como root.
RUN groupadd --system --gid 10001 netbot \
    && useradd --system --uid 10001 --gid netbot --home-dir /app --no-create-home netbot \
    && mkdir -p /var/lib/netbot \
    && chown netbot:netbot /var/lib/netbot

WORKDIR /app

# Versiones fijadas y revisadas (requirements.lock); sin resolución en el build.
COPY requirements.lock ./
RUN pip install --no-deps -r requirements.lock

COPY alembic.ini ./
COPY migrations ./migrations
COPY deploy/logging.json ./deploy/logging.json
COPY app ./app

USER netbot
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"]

# Un solo worker: las sesiones de invitados viven en memoria del proceso.
# --forwarded-allow-ips debe ser la IP fija del proxy (ver docker-compose.prod.yml).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--no-server-header", "--proxy-headers", "--forwarded-allow-ips", "172.28.0.10", \
     "--log-config", "deploy/logging.json"]
