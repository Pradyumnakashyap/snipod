FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml poetry.lock* ./

RUN pip install --no-cache-dir poetry \
    && poetry config virtualenvs.in-project true \
    && poetry install --no-root --only=main --no-interaction

# --- Final stage ---
FROM python:3.11-slim

ARG APP_UID=1000
ARG APP_GID=1000

RUN groupadd -g ${APP_GID} appgroup \
    && useradd -u ${APP_UID} -g appgroup -s /bin/false appuser

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app"

WORKDIR /app
COPY --from=builder /build/.venv .venv
COPY app/ .

EXPOSE 8080

USER appuser
CMD ["python", "main.py"]
