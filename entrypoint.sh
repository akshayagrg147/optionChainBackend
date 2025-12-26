#!/bin/bash

# Wait for database/redis to be ready
echo "Waiting for Redis..."
while ! nc -z db 6379; do
  sleep 0.1
done
echo "Redis is ready!"

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

