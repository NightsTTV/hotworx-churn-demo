# Stage 1: Build python packages and wheels
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Final runtime container
FROM python:3.11-slim AS runner

WORKDIR /app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8501

# Install runtime dependencies including curl for healthcheck and cron for the ETL scheduler
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from the builder
COPY --from=builder /opt/venv /opt/venv

# Copy all application code
COPY . .

# Expose the Streamlit service port
EXPOSE 8501

# Healthcheck to verify the Streamlit dashboard is serving traffic
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# Default command launches the Streamlit app
CMD ["streamlit", "run", "dashboard.py", "--server.port=8501", "--server.address=0.0.0.0"]
