# Docker Setup for Local Development

This project is now dockerized for easy local development.

## Prerequisites

- Docker Desktop (or Docker Engine + Docker Compose)
- Docker Compose v2 (usually included with Docker Desktop)

## Quick Start

1. **Build and start the containers:**
   ```bash
   docker-compose up --build
   ```

2. **Access the application:**
   - Django app: http://localhost:8000
   - Redis: localhost:6379

3. **Run migrations (if needed):**
   ```bash
   docker-compose exec web python manage.py migrate
   ```

4. **Create a superuser:**
   ```bash
   docker-compose exec web python manage.py createsuperuser
   ```

5. **Access Django shell:**
   ```bash
   docker-compose exec web python manage.py shell
   ```

## Common Commands

### Start containers in detached mode:
```bash
docker-compose up -d
```

### View logs:
```bash
docker-compose logs -f web
```

### Stop containers:
```bash
docker-compose down
```

### Stop and remove volumes (cleans database):
```bash
docker-compose down -v
```

### Rebuild containers:
```bash
docker-compose build --no-cache
```

### Run Django management commands:
```bash
docker-compose exec web python manage.py <command>
```

## Services

- **web**: Django application running on port 8000
- **db**: Redis server running on port 6379

## Volumes

- Project code is mounted as a volume for live code changes
- Media files are persisted in a Docker volume
- Redis data is persisted in a Docker volume

## Environment Variables

The following environment variables are set in docker-compose.yml:
- `REDIS_HOST=db` (Redis service name)
- `REDIS_PORT=6379`
- `DEBUG=1`
- `DJANGO_SETTINGS_MODULE=trading.settings`

## Notes

- Code changes are reflected immediately (no rebuild needed)
- Database migrations run automatically on container start
- Redis is used for Django Channels WebSocket support

