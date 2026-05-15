#!/bin/bash
# backup-redis.sh — Snapshot Redis data and store locally (with optional S3 upload)
#
# Usage:
#   ./scripts/backup-redis.sh                    # Local backup only
#   S3_BUCKET=my-bucket ./scripts/backup-redis.sh  # Local + S3 upload
#
# Cron example (daily at 2 AM):
#   0 2 * * * /path/to/scripts/backup-redis.sh >> /var/log/aion-backup.log 2>&1
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-.backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
REDIS_CONTAINER="${REDIS_CONTAINER:-aion-redis}"
S3_BUCKET="${S3_BUCKET:-}"
AWS_REGION="${AWS_REGION:-us-east-1}"

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/dump_$TIMESTAMP.rdb"

echo "[$(date +'%Y-%m-%d %H:%M:%S')] Starting Redis backup..."

# Ensure container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${REDIS_CONTAINER}$"; then
  echo "ERROR: Redis container '$REDIS_CONTAINER' not running"
  exit 1
fi

# Trigger BGSAVE
docker exec "$REDIS_CONTAINER" redis-cli BGSAVE > /dev/null

# Wait for save to complete
echo "Waiting for BGSAVE to complete..."
for i in $(seq 1 30); do
  LASTSAVE=$(docker exec "$REDIS_CONTAINER" redis-cli LASTSAVE | tr -d '[:space:]')
  CURRENT=$(date +%s)
  if [ "$((CURRENT - LASTSAVE))" -lt 3 ]; then
    break
  fi
  sleep 1
done

# Copy from container
docker cp "$REDIS_CONTAINER:/data/dump.rdb" "$BACKUP_FILE"
FILESIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "Backup saved: $BACKUP_FILE ($FILESIZE)"

# Compress
gzip "$BACKUP_FILE"
BACKUP_FILE="${BACKUP_FILE}.gz"
FILESIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "Compressed: $BACKUP_FILE ($FILESIZE)"

# Optional S3 upload
if [ -n "$S3_BUCKET" ]; then
  S3_KEY="aion-redis-backups/$TIMESTAMP.rdb.gz"
  echo "Uploading to s3://$S3_BUCKET/$S3_KEY..."
  aws s3 cp "$BACKUP_FILE" "s3://$S3_BUCKET/$S3_KEY" \
    --sse AES256 \
    --region "$AWS_REGION" \
    --metadata "date=$TIMESTAMP,hostname=$(hostname)" \
    --quiet
  echo "S3 upload complete"
fi

# Cleanup old backups
DELETED=$(find "$BACKUP_DIR" -name "dump_*.rdb.gz" -mtime +$RETENTION_DAYS -delete -print | wc -l)
if [ "$DELETED" -gt 0 ]; then
  echo "Cleaned up $DELETED old backups (>${RETENTION_DAYS} days)"
fi

echo "[$(date +'%Y-%m-%d %H:%M:%S')] Backup completed successfully"
