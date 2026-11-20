FROM python:3.12.10-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY ops ops
COPY fixtures fixtures
COPY migrations migrations
COPY tests tests
COPY scripts scripts
CMD ["uvicorn","ops.api:app","--host","0.0.0.0","--port","8000","--no-access-log"]
