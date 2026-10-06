# Pharmacy Billing App — single-container image.
#
#   Stage 1 (ui):     build the React frontend with Node.
#   Stage 2 (runtime): Flask + waitress serves the API and the built UI.
#
# Build:  docker build -t pharmacy-app .
# Run:    docker run -d --name pharmacy -p 5000:5000 \
#             -v pharmacy-data:/data -v pharmacy-uploads:/app/backend/uploads \
#             pharmacy-app

# ---------- Stage 1: build the frontend ----------
FROM node:20-alpine AS ui
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build   # -> /build/dist

# ---------- Stage 2: production runtime ----------
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=5000 \
    DATABASE_URL=sqlite:////data/pharmacy.db

WORKDIR /app/backend

# System deps kept minimal (no compilers needed — wheels only).
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app.py backend/serve.py backend/models.py backend/migrations.py ./

# Prebuilt UI from stage 1 (Flask serves ../frontend/dist).
COPY --from=ui /build/dist /app/frontend/dist

RUN mkdir -p /data /app/backend/uploads && \
    useradd --create-home --uid 10001 appuser && \
    chown -R appuser:appuser /app /data

VOLUME ["/data", "/app/backend/uploads"]
EXPOSE 5000
USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=4).status == 200 else 1)"

CMD ["python", "serve.py"]
