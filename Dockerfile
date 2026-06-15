FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "siglent_sds_mcp.server"]
