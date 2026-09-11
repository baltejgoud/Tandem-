FROM python:3.12-slim

# Install system utilities and libraries needed by headless Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Install dependencies with uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

# Install Playwright Chromium browser
RUN uv run playwright install chromium --with-deps

# Copy application source
COPY . .

# Expose Tandem and Simulator ports
EXPOSE 8000 8001 8003 8004

# Default command starts all simulators and the operator console
CMD ["uv", "run", "python", "scripts/start_services.py"]
