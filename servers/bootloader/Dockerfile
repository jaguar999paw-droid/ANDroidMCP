FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    fastboot \
    && rm -rf /var/lib/apt/lists/* \
    || (apt-get install -y android-tools-fastboot && rm -rf /var/lib/apt/lists/*)

WORKDIR /app
COPY servers/bootloader/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY servers/bootloader/server.py .

RUN mkdir -p /workspace && chmod 755 /workspace

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8111/mcp')" || exit 1

ENV MCP_PORT=8111
EXPOSE 8111

CMD ["python3", "server.py"]
