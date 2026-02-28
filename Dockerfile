FROM python:3.14-alpine

LABEL org.opencontainers.image.title="Seekarr" \
      org.opencontainers.image.description="Sonarr/Radarr missing media recovery and quality upgrade automation" \
      org.opencontainers.image.source="https://github.com/drew43713/seekarr"

WORKDIR /app
COPY seekarr.py /app/seekarr.py
COPY entrypoint.py /app/entrypoint.py

RUN chmod +x /app/seekarr.py /app/entrypoint.py \
    && mkdir -p /config /logs

ENV SEEKARR_CONFIG=/config/config.json

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD pgrep -x crond > /dev/null || pgrep -f seekarr.py > /dev/null || exit 1

ENTRYPOINT ["python", "/app/entrypoint.py"]
