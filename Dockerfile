FROM python:3.11-slim

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends make \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir pytest==8.3.3
COPY . .
RUN pytest -q
