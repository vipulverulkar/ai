FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EXPENSE_DB=/data/expenses.db \
    PORT=5000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /data \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app /data

COPY run.py gunicorn.conf.py entrypoint.sh ./
COPY app ./app
RUN chmod +x entrypoint.sh

EXPOSE 5000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=4)" || exit 1

ENTRYPOINT ["./entrypoint.sh"]

CMD ["gunicorn", "-c", "gunicorn.conf.py", "run:app"]
