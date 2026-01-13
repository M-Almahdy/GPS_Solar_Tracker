#!/bin/bash
# Backup script for Solar Tracker
BACKUP_DIR="/home/pi/solar-tracker/backups"
SOURCE_DIR="/home/pi/solar-tracker"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

echo "Creating backup..."
tar -czf "$BACKUP_DIR/backup_$DATE.tar.gz" \
    --exclude="backups/*" \
    --exclude="logs/*" \
    --exclude="data/*.json" \
    $SOURCE_DIR

echo "Backup created: $BACKUP_DIR/backup_$DATE.tar.gz"

# Keep only last 7 backups
cd $BACKUP_DIR
ls -t backup_*.tar.gz | tail -n +8 | xargs -r rm

echo "Backup complete."