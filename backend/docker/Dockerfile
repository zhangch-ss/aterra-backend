ARG PYTHON_VERSION=3.11-slim
FROM python:${PYTHON_VERSION} AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:${PATH}"

# Optional: use mirror inside CN to speed up builds
ARG USE_CN_MIRROR=false
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential gcc \
    libpq-dev libjpeg-dev zlib1g-dev libpng-dev libgeos-dev \
    && rm -rf /var/lib/apt/lists/*
RUN if [ "$USE_CN_MIRROR" = "true" ]; then \
      pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple; \
    fi

# ----- Builder stage: create venv and install deps via Poetry export -----
FROM base AS builder
WORKDIR /code

# Install Poetry in builder only
RUN pip install --no-cache-dir "poetry==1.7.1"

COPY pyproject.toml poetry.lock* ./

# Export dependencies (main only) and install into a virtualenv
RUN python -m venv /opt/venv \
 && . /opt/venv/bin/activate \
 && poetry export -f requirements.txt --output requirements.txt --without-hashes \
 && pip install --no-cache-dir -r requirements.txt

# ----- Runtime stage: copy venv and source -----
FROM base AS runtime
WORKDIR /code

# Non-root runtime user
RUN adduser --disabled-password --gecos "" appuser && chown -R appuser:appuser /code
USER appuser

# Copy installed site-packages and project source
COPY --from=builder /opt/venv /opt/venv
COPY . /code

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
