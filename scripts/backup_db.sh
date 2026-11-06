#!/bin/bash
set -e
BACKUP_DIR="/var/backups/taqueria"
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DB_PATH="/opt/taqueria/backend/data/taqueria.db"

if [ -f "$DB_PATH" ]; then
    cp "$DB_PATH" "$BACKUP_DIR/taqueria_$TIMESTAMP.db"
    echo "[$(date)] Respaldo exitoso: $BACKUP_DIR/taqueria_$TIMESTAMP.db"
    find "$BACKUP_DIR" -name "taqueria_*.db" -type f -mtime +30 -delete 2>/dev/null || true
fi
