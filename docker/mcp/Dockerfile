FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/mcp_server

RUN pip install --no-cache-dir \
    "httpx>=0.28.0,<1" \
    "mcp==1.29.1" \
    "uvicorn>=0.35.0,<1"

COPY mcp_server /app/mcp_server

EXPOSE 8100

CMD ["python", "-m", "mafia_game"]
