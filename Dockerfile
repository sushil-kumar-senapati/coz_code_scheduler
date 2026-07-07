# Stage 1: build wheels (scikit-learn + numpy are large — pre-build avoids reinstall on redeploy)
FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# Stage 2: runtime
FROM python:3.12-slim
WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

COPY . .

# Cloud Run Service: starts HTTP server + nightly schedule loop
CMD ["python", "server.py"]
