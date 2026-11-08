# ==========================================================
# Dockerfile - Imagen de Producción Endurecida (Non-Root)
# ==========================================================
FROM python:3.12-slim-bookworm

# Evitar escritura de bytecode (.pyc) y buffering de salida
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_ENV=production

WORKDIR /app

# Instalar dependencias del sistema para PostgreSQL (libpq)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar requerimientos limpios
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt psycopg2-binary gunicorn

# Crear usuario de sistema sin privilegios de root
RUN groupadd -r josepo && useradd -r -g josepo josepo

# Copiar únicamente el código fuente de la aplicación (filtrado por .dockerignore)
COPY app ./app
COPY run.py seed_data.py ./

RUN chown -R josepo:josepo /app
USER josepo

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health')" || exit 1

CMD ["python", "run.py"]

