# ---------- Stage 1: build wheels ----------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# ---------- Stage 2: minimal runtime ----------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EXPENSE_DB=/data/expenses.db \
    PORT=5000

WORKDIR /app

# Non-root user; /data (db + sessions + backups) owned by it.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data

COPY --from=builder /build/requirements.txt /tmp/requirements.txt
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links /wheels \
        -r /tmp/requirements.txt \
    && rm -rf /wheels /tmp/requirements.txt

COPY --chown=appuser:appuser requirements.txt run.py gunicorn.conf.py entrypoint.sh ./
COPY --chown=appuser:appuser app ./app
RUN chmod +x entrypoint.sh \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 5000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=4)" || exit 1

ENTRYPOINT ["./entrypoint.sh"]

CMD ["gunicorn", "-c", "gunicorn.conf.py", "run:app"]
