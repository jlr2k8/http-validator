FROM node:22-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS final
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir -e ".[web]"

COPY --from=frontend /app/frontend/dist frontend/dist

ENV PORT=8080
ENV API_HOST=0.0.0.0
ENV STATIC_ROOT=/app/frontend/dist

EXPOSE 8080
CMD ["http-validator-api"]