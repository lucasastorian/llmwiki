FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer libreoffice-impress libreoffice-calc \
    openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

RUN useradd -m -s /bin/bash converter
WORKDIR /app
RUN pip install --no-cache-dir uv pip-audit
COPY requirements.lock ./requirements.lock
RUN uv pip install --system --require-hashes -r requirements.lock
RUN pip-audit -r requirements.lock --strict --desc
COPY . ./converter/

USER converter
EXPOSE 8000
CMD python -m uvicorn converter.main:app --host 0.0.0.0 --port ${PORT:-8000}
