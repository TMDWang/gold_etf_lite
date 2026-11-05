FROM node:24-bookworm-slim AS frontend
WORKDIR /build
RUN npm install -g pnpm@11.25.0
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.12-slim-bookworm
ARG PYPI_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Shanghai
WORKDIR /app
# PostgreSQL 17 tools must match the database for consistent custom-format dumps.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg tini && \
    install -d /usr/share/postgresql-common/pgdg && \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc && \
    echo 'deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main' > /etc/apt/sources.list.d/pgdg.list && \
    apt-get update && apt-get install -y --no-install-recommends postgresql-client-17 && \
    rm -rf /var/lib/apt/lists/*
COPY requirements.lock ./
RUN pip install --no-cache-dir --index-url "$PYPI_INDEX_URL" -r requirements.lock
COPY . .
COPY --from=frontend /build/dist ./frontend/dist
# NAS filesystems can supply mode 000 in the build context. These are application
# sources only (.dockerignore excludes private data and configuration).
RUN useradd --uid 10001 --create-home appuser && \
    chmod -R a+rX /app && \
    su -s /bin/sh appuser -c 'SECRET_KEY=build-only DEBUG=1 python -c "from config.wsgi import application; from pathlib import Path; assert Path(\"frontend/dist/index.html\").read_bytes()"' && \
    SECRET_KEY=build-only DEBUG=1 python manage.py collectstatic --noinput && \
    mkdir -p /backups && chown appuser:appuser /backups
EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "deploy/start.sh"]
