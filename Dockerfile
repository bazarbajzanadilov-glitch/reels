FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements.lock requirements-align.txt .
RUN pip install --no-cache-dir -r requirements.lock
ARG WITH_ALIGNMENT=0
RUN if [ "$WITH_ALIGNMENT" = "1" ]; then pip install --no-cache-dir -r requirements-align.txt; fi
COPY factory ./factory
COPY web ./web
COPY assets ./assets
COPY server.py worker.py make_video.py manage.py deploy.py ./
ARG APP_UID=10001
ARG APP_GID=10001
RUN chmod -R a+rX /app/factory /app/web /app/assets && chmod a+r /app/*.py
RUN groupadd -g "$APP_GID" factory && useradd -u "$APP_UID" -g factory -M factory \
    && mkdir -p /app/jobs /app/cache /app/.models /app/backups && chown factory:factory /app/jobs /app/cache /app/.models /app/backups
USER factory
ENV PORT=8000 PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request; __import__('json').load(urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=4))['ready'] or exit(1)"
CMD ["python", "server.py"]
