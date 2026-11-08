FROM node:24-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim AS backend
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.lock.txt ./requirements.lock.txt
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY backend/ ./backend/
RUN pip install --no-cache-dir --no-deps ./backend && useradd --uid 10001 --create-home cqa && mkdir -p /app/data && chown cqa:cqa /app/data
COPY --from=frontend /build/dist /app/frontend
ENV CQA_FRONTEND_DIR=/app/frontend CQA_DB_PATH=/app/data/cqa.sqlite3
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "cqa.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log", "--limit-concurrency", "64", "--timeout-keep-alive", "5"]
