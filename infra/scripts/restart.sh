#!/bin/sh
set -e

# Build backend image
docker build -f backend/docker/Dockerfile.runtime -t project-app:latest .

# Start (or update) Milvus stack separately
docker-compose -f infra/milvus/docker-compose.yml up -d

# Restart application stack
docker-compose -f infra/docker-compose.yml down
# Tip: use `docker-compose -f infra/docker-compose.yml down -v` only when you intentionally want to wipe DB volumes
docker-compose -f infra/docker-compose.yml up -d
