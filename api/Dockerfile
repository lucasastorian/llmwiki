FROM python:3.11-slim-bookworm AS base
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

RUN pip install --no-cache-dir uv pip-audit

COPY requirements.lock .
RUN uv pip install --system --require-hashes -r requirements.lock
RUN pip-audit -r requirements.lock --strict --desc

# Only ships if pip-audit passed above.
FROM base AS runtime

# Hosted-only image: PDF/Office parsing belongs exclusively to the converter.
RUN pip uninstall --yes opendataloader-pdf

COPY . .

ENV MODE=hosted
EXPOSE 8000
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --timeout-graceful-shutdown 30
