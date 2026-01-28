FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
# Use requirements-docker.txt which excludes Windows-only packages like pywin32
COPY requirements-docker.txt /app/requirements.txt

# Install autobahn 22.4.2+ first (required by daphne)
# Install all requirements (kiteconnect is commented out in requirements-docker.txt)
# Then install kiteconnect with --no-deps since autobahn is already installed
RUN pip install --no-cache-dir "autobahn>=22.4.2" && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --no-deps "kiteconnect==5.0.1"

# Copy entrypoint script first and fix line endings
COPY entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && \
    chmod +x /entrypoint.sh

# Copy project
COPY . /app/

# Create media directory
RUN mkdir -p /app/media

# Verify CSV files are present (for debugging)
RUN ls -la /app/*.csv 2>/dev/null || echo "Warning: No CSV files found in /app"
RUN ls -la /app/*.json 2>/dev/null || echo "Warning: No JSON files found in /app"

# Expose port
EXPOSE 8000

# Run entrypoint script (use /entrypoint.sh which won't be overwritten by volume mount)
ENTRYPOINT ["/entrypoint.sh"]

