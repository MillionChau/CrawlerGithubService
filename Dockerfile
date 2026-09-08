# =========================
# 1. Dependencies
# =========================
FROM python:3.12-slim AS dependencies

WORKDIR /build

COPY requirements.txt .

RUN pip install --prefix=/install -r requirements.txt


# =========================
# 2. Build / Test
# =========================
FROM python:3.12-slim AS build

WORKDIR /app

COPY --from=dependencies /install /usr/local

COPY . .

# RUN pytest


# =========================
# 3. Runtime
# =========================
FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY --from=build /app .
COPY --from=dependencies /install /usr/local

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]