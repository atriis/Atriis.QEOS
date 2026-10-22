# Python 3.11 to match the version this service is developed and tested against; the
# image previously specified 3.9, which nothing ever ran.
FROM python:3.11-slim

WORKDIR /app

# apt-get upgrade: the base image's patched packages (Trivy fails the build on fixable CRITICAL findings, ADR-038)
RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# The repo layout is mirrored inside the image so that requirements.txt's
# `-e ../../../shared` resolves to /app/shared, exactly as it resolves to the repo's
# shared/ during local development. One relative path, one source of truth.
COPY shared/ ./shared/
COPY platforms/auth-service/auth-service/requirements.txt ./platforms/auth-service/auth-service/

WORKDIR /app/platforms/auth-service/auth-service
RUN pip install --no-cache-dir -r requirements.txt

COPY platforms/auth-service/auth-service/src/ ./src/
COPY platforms/auth-service/auth-service/alembic/ ./alembic/
COPY platforms/auth-service/auth-service/alembic.ini ./alembic.ini

# Non-root (ADR-038): the same uid in every QEOS image, so a Kubernetes securityContext can name it. Nothing is
# written at runtime outside /tmp, so the root filesystem can be read-only; no bytecode cache either
RUN groupadd --system --gid 10001 qeos \
    && useradd --system --uid 10001 --gid qeos --no-create-home --shell /usr/sbin/nologin qeos
ENV PYTHONDONTWRITEBYTECODE=1
USER 10001

EXPOSE 8000

# `python src/auth/main.py` put src/auth/ first on sys.path rather than the working
# directory, so its own `from src.auth...` import failed with ModuleNotFoundError: the
# container never started. uvicorn resolves the app from the working directory instead.
CMD ["uvicorn", "src.auth.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
