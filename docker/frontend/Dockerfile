FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY frontend_user/requirements.txt /tmp/frontend-requirements.txt
RUN pip install --no-cache-dir -r /tmp/frontend-requirements.txt

COPY frontend_user /app/frontend_user

EXPOSE 8501

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=12 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"

CMD ["streamlit", "run", "frontend_user/app.py", "--server.address", "0.0.0.0", "--server.port", "8501", "--server.headless", "true"]
