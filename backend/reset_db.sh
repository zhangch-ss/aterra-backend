#!/usr/bin/env bash
set -euo pipefail

# This script will WIPE the Postgres data volume used by docker-compose.
# Use it ONLY if you intentionally want to reset the database.
# It is safe to run from the project root (where docker-compose.yml resides).

read -r -p "WARNING: This will DELETE all database data. Continue? (y/N) " ans
if [[ "${ans:-N}" != "y" && "${ans:-N}" != "Y" ]]; then
  echo "Aborted."
  exit 0
fi

echo "Stopping stack and removing containers + anonymous volumes..."
docker-compose down -v

# Try to remove the named volume created by docker-compose
# Compose usually names the volume as <project>_db_docker; also try plain db_docker
PROJECT_NAME=${COMPOSE_PROJECT_NAME:-$(basename "$PWD")}
CANDIDATES=("db_docker" "${PROJECT_NAME}_db_docker")
for v in "${CANDIDATES[@]}"; do
  if docker volume inspect "$v" >/dev/null 2>&1; then
    echo "Removing volume: $v"
    docker volume rm "$v" || true
  fi
done

# Remove any residual volumes that match db_docker pattern
RESIDUAL=$(docker volume ls -q | grep -E 'db_docker' || true)
if [[ -n "$RESIDUAL" ]]; then
  echo "$RESIDUAL" | xargs -r docker volume rm || true
fi

echo "Rebuilding app image..."
docker build -f docker/Dockerfile.runtime -t project-app:latest .

echo "Starting stack..."
docker-compose up -d

echo "Done. Database has been reinitialized."
