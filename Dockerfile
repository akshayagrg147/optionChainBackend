FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
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

# Copy project
COPY . /app/

# Make entrypoint script executable
RUN chmod +x /app/entrypoint.sh

# Create media directory
RUN mkdir -p /app/media

# Expose port
EXPOSE 8000

# Run entrypoint script
ENTRYPOINT ["/app/entrypoint.sh"]

