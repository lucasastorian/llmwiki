FROM python:3.11-slim-bookworm
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080
COPY requirements.txt .
RUN pip install --upgrade pip pip-audit && \
    pip install --no-cache-dir -r requirements.txt && \
    pip-audit -r requirements.txt --strict --desc
COPY . .
EXPOSE 8080
CMD ["python", "-m", "server"]
