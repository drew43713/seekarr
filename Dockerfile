FROM python:3.11-alpine

WORKDIR /app
COPY seekarr.py /app/seekarr.py
COPY entrypoint.py /app/entrypoint.py

RUN chmod +x /app/seekarr.py /app/entrypoint.py \
    && mkdir -p /config /logs

ENV SEEKARR_CONFIG=/config/config.json

ENTRYPOINT ["python", "/app/entrypoint.py"]
