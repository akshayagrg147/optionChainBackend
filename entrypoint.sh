#!/bin/bash

# Get Redis host and port from environment variables, with defaults
REDIS_HOST=${REDIS_HOST:-db}
REDIS_PORT=${REDIS_PORT:-6379}

# Wait for database/redis to be ready
echo "Waiting for Redis at ${REDIS_HOST}:${REDIS_PORT}..."
MAX_ATTEMPTS=60
ATTEMPT=0

while ! nc -z "${REDIS_HOST}" "${REDIS_PORT}" 2>/dev/null; do
  ATTEMPT=$((ATTEMPT + 1))
  if [ $ATTEMPT -ge $MAX_ATTEMPTS ]; then
    echo "Warning: Could not connect to Redis at ${REDIS_HOST}:${REDIS_PORT} after ${MAX_ATTEMPTS} attempts."
    echo "Continuing anyway - Redis may not be available or may start later."
    break
  fi
  sleep 1
done

if nc -z "${REDIS_HOST}" "${REDIS_PORT}" 2>/dev/null; then
  echo "Redis is ready!"
else
  echo "Note: Redis connection check failed, but continuing..."
fi

# Run migrations
echo "Running migrations..."
python manage.py migrate --noinput

# Collect static files (if STATIC_ROOT is configured)
echo "Collecting static files..."
python manage.py collectstatic --noinput 2>/dev/null || echo "Skipping collectstatic (STATIC_ROOT not configured or no static files)"

# Create superuser if it doesn't exist (optional, for development)
# Uncomment the following lines if you want to auto-create a superuser
# echo "Creating superuser..."
# python manage.py shell << EOF
# from authentication.models import User
# if not User.objects.filter(username='admin').exists():
#     User.objects.create_superuser('admin', 'admin@example.com', 'admin')
# EOF

# Execute the main command
exec "$@"

