# qeos-collector for runners without Python:
#   docker run --rm -v "$PWD:/work" -w /work -e QEOS_URL -e QEOS_API_KEY \
#     ghcr.io/carneiru/qeos-collector:0.5.1 upload "reports/**/*.xml"
FROM python:3.12-slim

# git: code-change data and commit metadata (best effort without it)
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY . /src
RUN pip install --no-cache-dir /src && rm -rf /src

# Mounted workspaces belong to the host user; git refuses to read them otherwise
RUN git config --system safe.directory '*'

ENTRYPOINT ["qeos-collector"]
CMD ["--help"]
