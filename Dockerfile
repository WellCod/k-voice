FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-dev python3-pip curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# --- dependências (camada cacheável) ---
FROM base AS deps

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project

# --- imagem final ---
FROM deps AS runtime

COPY src/ src/
RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "kvoice.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
