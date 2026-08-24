# Ultron AI Agent - Production Dockerfile (self-updating)
# Build context = this repo clone. The image contains the full git history
# so the in-app "UPDATE" button can pull new versions from the cloud.

# Stage 1: Builder
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install into a relocatable prefix we can hand to the runtime stage
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Production
FROM python:3.11-slim AS production

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/app

# git is required for the built-in self-update system
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory '*'

# Non-root runtime user; home is /app so `pip install --user` (used by the
# updater) lands in /app/.local which is writable by this user.
RUN groupadd -r ultron && useradd -r -g ultron -d /app -s /sbin/nologin ultron

WORKDIR /app

# Application code (incl. .git -> enables self-update)
COPY . .
COPY --from=builder /install /usr/local

# Runtime dirs that are volume-mounted in compose; created if absent.
# .local must be owned by ultron so updates can install dependencies.
RUN mkdir -p data skills recipes proposals output logs .local && \
    chown -R ultron:ultron /app

USER ultron

ENV PATH=/app/.local/bin:/usr/local/bin:$PATH

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:5000/api/state', timeout=5)" || exit 1

CMD ["python", "web.py"]
