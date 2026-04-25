FROM python:3.11-slim-bookworm AS base
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080

RUN pip install --no-cache-dir uv pip-audit

COPY requirements.lock .
RUN uv pip install --system --require-hashes -r requirements.lock
RUN pip-audit -r requirements.lock --strict --desc

# ---------------------------------------------------------------------------
# Runtime — only ships if deps are clean
# ---------------------------------------------------------------------------
FROM base AS runtime

COPY . .

ENV MODE=hosted
EXPOSE 8080
CMD ["python", "-m", "server"]
