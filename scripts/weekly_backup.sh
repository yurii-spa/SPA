#!/bin/bash
# Weekly SPA_Claude backup — runs every Saturday at 10:00 AM
DATE=$(date +%Y-%m-%d)
BACKUP_DIR="/Users/yuriikulieshov/Documents/SPA_Backups"
SOURCE_DIR="/Users/yuriikulieshov/Documents"
LOG_FILE="/tmp/spa_backup.log"

echo "$(date): Starting SPA_Claude backup..." >> "$LOG_FILE"

mkdir -p "$BACKUP_DIR"

tar --exclude='SPA_Claude/.git' \
    --exclude='SPA_Claude/__pycache__' \
    --exclude='SPA_Claude/**/__pycache__' \
    --exclude='SPA_Claude/*.log' \
    --exclude='SPA_Claude/node_modules' \
    -czf "$BACKUP_DIR/SPA_Claude_backup_$DATE.tar.gz" \
    -C "$SOURCE_DIR" SPA_Claude/

STATUS=$?
if [ $STATUS -eq 0 ]; then
    # Keep only last 4 backups (4 weeks)
    ls -t "$BACKUP_DIR"/SPA_Claude_backup_*.tar.gz 2>/dev/null | tail -n +5 | xargs rm -f
    SIZE=$(du -sh "$BACKUP_DIR/SPA_Claude_backup_$DATE.tar.gz" | cut -f1)
    echo "$(date): Backup created: SPA_Claude_backup_$DATE.tar.gz ($SIZE)" >> "$LOG_FILE"
    echo "Backup created: SPA_Claude_backup_$DATE.tar.gz ($SIZE)"
else
    echo "$(date): Backup FAILED with exit code $STATUS" >> "$LOG_FILE"
    echo "Backup FAILED with exit code $STATUS"
    exit $STATUS
fi
