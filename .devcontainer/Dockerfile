# Multi-stage Dockerfile for CasambiBt development
# Builder stage: Install dependencies and build Python packages
FROM python:3.12-slim AS builder

# Install system build dependencies for Python packages
RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    libdbus-1-dev \
    pkg-config \
    bluez \
    && rm -rf /var/lib/apt/lists/*

# Install pipenv
RUN pip install --no-cache-dir pipenv

# Copy Pipfile for dependency installation
COPY Pipfile /app/Pipfile
COPY Pipfile.lock /app/Pipfile.lock

# Set working directory
WORKDIR /app

# Install Python dependencies system-wide (including dev dependencies)
RUN pipenv install --dev --system --deploy

# Final stage: Runtime environment
FROM python:3.12-slim

# Install runtime system dependencies
RUN apt-get update && apt-get install -y \
    git \
    bluez \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder stage
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Set default working directory (will be overridden by devcontainer mount)
WORKDIR /workspaces/casambi-bt

# Default command
CMD ["python"]