# android-userspace-server — uses locally cached python:3.12-slim
FROM python:3.12-slim AS builder

WORKDIR /build
COPY servers/userspace/requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.12-slim

# ADB via apt (debian package - no registry pull needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    adb \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

WORKDIR /app
COPY servers/userspace/server.py .
COPY servers/userspace/tools/ ./tools/

RUN mkdir -p /workspace && chmod 755 /workspace

ENV MCP_PORT=8110
ENV ADB_SERVER_HOST=127.0.0.1
ENV ADB_SERVER_PORT=5037

EXPOSE 8110
CMD ["python3", "server.py"]
