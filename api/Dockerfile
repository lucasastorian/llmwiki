FROM python:3.11-slim-bookworm
WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip pip-audit && \
    pip install --no-cache-dir -r requirements.txt && \
    pip-audit -r requirements.txt --strict --desc
COPY . .
EXPOSE 8000
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --timeout-graceful-shutdown 30
