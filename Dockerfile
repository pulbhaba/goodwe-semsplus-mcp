FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY goodwe_mcp ./goodwe_mcp
RUN pip install --no-cache-dir .
CMD ["python", "-m", "goodwe_mcp.server"]
