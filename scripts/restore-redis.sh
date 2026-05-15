#!/bin/bash
# restore-redis.sh — Restore Redis from a backup file
#
# Usage:
#   ./scripts/restore-redis.sh .backups/dump_20260514_020000.rdb.gz
#   S3_KEY=bucket/key ./scripts/restore-redis.sh /tmp/restore.rdb.gz
set -euo pipefail

BACKUP_FILE="${1:-}"
REDIS_CONTAINER="${REDIS_CONTAINER:-aion-redis}"
S3_KEY="${S3_KEY:-}"

if [ -z "$BACKUP_FILE" ] && [ -z "$S3_KEY" ]; then
  echo "Usage: $0 <backup_file.rdb[.gz]>"
  echo "  Or:  S3_KEY=bucket/path $0 /tmp/output.rdb.gz"
  exit 1
fi

# Download from S3 if needed
if [ -n "$S3_KEY" ]; then
  BACKUP_FILE="${BACKUP_FILE:-/tmp/aion-restore.rdb.gz}"
  echo "Downloading from s3://$S3_KEY..."
  aws s3 cp "s3://$S3_KEY" "$BACKUP_FILE"
fi

if [ ! -f "$BACKUP_FILE" ]; then
  echo "ERROR: Backup file not found: $BACKUP_FILE"
  exit 1
fi

echo "WARNING: This will stop AION and restore Redis from backup."
echo "Backup file: $BACKUP_FILE"
read -p "Continue? [y/N] " -n 1 -r
echo
if [ "$REPLY" != "y" ] && [ "$REPLY" != "Y" ]; then
  echo "Aborted."
  exit 0
fi

# Decompress if needed
RESTORE_FILE="$BACKUP_FILE"
if [[ "$BACKUP_FILE" == *.gz ]]; then
  RESTORE_FILE="${BACKUP_FILE%.gz}"
  echo "Decompressing..."
  gunzip -c "$BACKUP_FILE" > "$RESTORE_FILE"
fi

echo "Stopping services..."
docker compose down --timeout=10 2>/dev/null || docker-compose down --timeout=10 2>/dev/null || true

echo "Starting Redis only..."
docker compose up -d redis 2>/dev/null || docker-compose up -d redis 2>/dev/null
sleep 3

echo "Stopping Redis server inside container (to replace dump)..."
docker exec "$REDIS_CONTAINER" redis-cli SHUTDOWN NOSAVE 2>/dev/null || true
sleep 2

echo "Copying backup into container volume..."
docker cp "$RESTORE_FILE" "$REDIS_CONTAINER:/data/dump.rdb"

echo "Restarting all services..."
docker compose up -d 2>/dev/null || docker-compose up -d 2>/dev/null

echo "Waiting for services to be ready..."
sleep 10

echo "Verifying restore..."
DBSIZE=$(docker exec "$REDIS_CONTAINER" redis-cli DBSIZE 2>/dev/null || echo "unknown")
echo "Redis DBSIZE: $DBSIZE"

echo ""
echo "Restore completed. Verify application health:"
echo "  curl http://localhost:8080/health"

# Cleanup temp file
if [[ "$BACKUP_FILE" == *.gz ]] && [ -f "$RESTORE_FILE" ]; then
  rm -f "$RESTORE_FILE"
fi
