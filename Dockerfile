FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml ./
RUN uv sync --extra dev

COPY src/ ./src/

  CMD ["uv", "run", "uvicorn", "quota.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "src"]
