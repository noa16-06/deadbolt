# syntax=docker/dockerfile:1
#
# Backend image. Build context is the PROJECT ROOT, not backend/:
# app/config.py resolves PROJECT_ROOT two levels above itself and puts the
# SQLite file underneath it, so the layout inside the image has to match the
# one in the repository.
#
#   docker build -f backend/Dockerfile .

FROM python:3.12-slim

# The database is a bind mount from the host, so the user inside has to be the
# one that owns ./data outside. 1000 is the first user on most Linux boxes;
# `id -u` says whether that is true here.
ARG UID=1000
ARG GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# docs/security.md: the backend runs as its own unprivileged user.
RUN groupadd --gid "${GID}" app \
    && useradd --uid "${UID}" --gid "${GID}" --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app/backend

# Dependencies before the source, so editing a file does not reinstall them.
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ /app/backend/
COPY docker/backend-entrypoint.sh /usr/local/bin/backend-entrypoint.sh

RUN chmod +x /usr/local/bin/backend-entrypoint.sh \
    && mkdir -p /app/data \
    && chown -R app:app /app

USER app

EXPOSE 8000

# Checks the database too, not just whether the process answers.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"]

ENTRYPOINT ["/usr/local/bin/backend-entrypoint.sh"]
CMD ["python", "run.py"]
