# Python 3.11 to match the version this service is developed and tested against; the
# image previously specified 3.9, which nothing ever ran.
FROM python:3.11-slim

WORKDIR /app

# apt-get upgrade: python:3.11-slim is rebuilt only now and then, and Trivy fails the build on a fixable CRITICAL finding
# (ADR-038; linux-libc-dev, pulled in by gcc, was one). Not pinned: the patched packages are the point
RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# The repo layout is mirrored inside the image so that requirements.txt's
# `-e ../../shared` resolves to /app/shared, exactly as it resolves to the repo's
# shared/ during local development. One relative path, one source of truth.
COPY shared/ ./shared/
COPY platforms/organization-service/requirements.txt ./platforms/organization-service/

WORKDIR /app/platforms/organization-service
RUN pip install --no-cache-dir -r requirements.txt

# Application code and the migration tooling, so `alembic upgrade head` can run from the image
COPY platforms/organization-service/src/ ./src/
COPY platforms/organization-service/alembic/ ./alembic/
COPY platforms/organization-service/alembic.ini ./alembic.ini

# Non-root (ADR-038): the same uid in every QEOS image, so a Kubernetes securityContext can name it. Nothing is
# written at runtime outside /tmp, so the root filesystem can be read-only; no bytecode cache either
RUN groupadd --system --gid 10001 qeos \
    && useradd --system --uid 10001 --gid qeos --no-create-home --shell /usr/sbin/nologin qeos
ENV PYTHONDONTWRITEBYTECODE=1
USER 10001

EXPOSE 8000

CMD ["uvicorn", "src.organization.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
