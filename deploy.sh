#!/bin/bash
set -e
echo "=== 1. Respaldo de seguridad automatico ==="
/opt/taqueria/scripts/backup_db.sh

echo "=== 2. Descargando cambios de GitHub ==="
cd /opt/taqueria
git pull origin main

echo "=== 3. Actualizando contenedor Docker ==="
docker-compose build
docker rm -f taqueria_app 2>/dev/null || true
docker container prune -f
docker-compose up -d

echo "=== Despliegue completado ==="
docker ps --filter name=taqueria_app
