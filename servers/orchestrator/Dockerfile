FROM python:3.12-slim

WORKDIR /app
COPY servers/orchestrator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY servers/orchestrator/server.py .

RUN mkdir -p /workspace && chmod 755 /workspace

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8112/mcp')" || exit 1

ENV MCP_PORT=8112
ENV ORCHESTRATOR_NAMESPACE=androidmcp
EXPOSE 8112

CMD ["python3", "server.py"]
