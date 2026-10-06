FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EXPENSE_DB=/data/expenses.db

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /data

COPY app.py ./
COPY templates ./templates
COPY static ./static

EXPOSE 5000

# Persist SQLite database outside the container layer.
# Override at run time with: -e EXPENSE_DB=/data/expenses.db -v <volume|host-path>:/data
VOLUME ["/data"]

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "app:app"]
