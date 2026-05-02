FROM python:3.11-slim

WORKDIR /app

# Install system deps + dependencies
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY brain/ brain/
COPY shared/ shared/
COPY config/ config/

# Expose API port
EXPOSE 8780

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8780/health || exit 1

# Run with uvicorn
CMD ["python", "-m", "uvicorn", "brain.api.server:app", "--host", "0.0.0.0", "--port", "8780"]
