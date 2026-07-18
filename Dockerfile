FROM python:3.12-slim

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash planner

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only backend source directories
COPY planner_api/ ./planner_api/
COPY planner_platform/ ./planner_platform/
COPY planner_engine/ ./planner_engine/
COPY planner_mcp/ ./planner_mcp/
COPY planner_integrations/ ./planner_integrations/
COPY adapters/ ./adapters/
COPY config/ ./config/

# Switch to non-root user
USER planner

# Cloud Run sets PORT automatically; default to 8000 for local testing
ENV PORT=8000

# Use exec form so signals propagate properly
CMD ["sh", "-c", "uvicorn planner_api.app:app --host 0.0.0.0 --port $PORT"]
