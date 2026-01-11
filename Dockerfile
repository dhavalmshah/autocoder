FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        bash \
        git \
        nodejs \
        npm \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI
# (Subscription-based auth is done via `claude login` at runtime and persisted via a volume)
RUN curl -fsSL https://claude.ai/install.sh | bash

# Ensure common install locations are on PATH
ENV PATH="/root/.local/bin:/usr/local/bin:${PATH}"

# Make `claude` available even if a login shell resets PATH
RUN ln -sf /root/.local/bin/claude /usr/local/bin/claude \
    && command -v claude

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY ui/package.json ui/package-lock.json* ./ui/
RUN cd ui \
    && if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY . .

RUN cd ui && npm run build

EXPOSE 8888

CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8888"]
