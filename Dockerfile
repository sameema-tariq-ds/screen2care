FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    DEV_RELOAD=0

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY pyproject.toml ./
COPY app ./app

RUN pip install --upgrade pip \
    && pip install --no-cache-dir --prefer-binary --index-url https://pypi.org/simple . \
    && chown -R app:app /app

USER app
EXPOSE 8000

CMD ["sh", "-c", "if [ \"$DEV_RELOAD\" = \"1\" ]; then exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --reload --reload-dir /app/app --proxy-headers; else exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers; fi"]
