#!/usr/bin/env bash
# Dumps every QEOS database into one compressed file, copies the screenshot storage (MinIO volume, ADR-036)
# into a second one, and keeps the last 14 days of both.
# Run from cron (see deploy/README.md); safe to run while the platform serves traffic.
# --local backs up a local stack (docker-compose.yml only, no QEOS_DOMAIN needed).
set -euo pipefail
cd "$(dirname "$0")/.."

compose=(-f docker-compose.yml -f deploy/docker-compose.prod.yml)
case "${1:-}" in
  "") ;;
  --local) compose=(-f docker-compose.yml) ;;
  *) echo "usage: $0 [--local]" >&2; exit 2 ;;
esac

# QAV_BACKUP_* are the names before the QEOS rename, still read when the new ones are unset
dir="${QEOS_BACKUP_DIR:-${QAV_BACKUP_DIR:-$PWD/backups}}"
keep_days="${QEOS_BACKUP_KEEP_DAYS:-${QAV_BACKUP_KEEP_DAYS:-14}}"
mkdir -p "$dir"

file="$dir/qeos-$(date -u +%Y%m%dT%H%MZ).sql.gz"
trap 'rm -f "$file.partial"' EXIT  # a failed dump leaves nothing behind
# pg_dumpall: all five service databases plus roles, consistent per database
docker compose "${compose[@]}" exec -T postgres pg_dumpall -U postgres | gzip > "$file.partial"
mv "$file.partial" "$file"  # a half-written dump never looks like a good one

# Screenshots live in MinIO's volume, not in PostgreSQL. A stack that never started minio has no volume: skipped
minio_volume=qa-vision_qeos_minio_data
minio_file=""
if docker volume inspect "$minio_volume" >/dev/null 2>&1; then
  minio_file="$dir/qeos-minio-$(date -u +%Y%m%dT%H%MZ).tar.gz"
  trap 'rm -f "$file.partial" "$minio_file.partial"' EXIT
  docker run --rm -v "$minio_volume":/data:ro -v "$dir":/backup alpine:3.20 \
    tar czf "/backup/$(basename "$minio_file").partial" -C /data .
  mv "$minio_file.partial" "$minio_file"
fi

# qav-*.sql.gz: dumps written before the QEOS rename age out the same way
find "$dir" \( -name 'qeos-*.sql.gz' -o -name 'qav-*.sql.gz' -o -name 'qeos-minio-*.tar.gz' \) -mtime +"$keep_days" -delete
echo "backup written: $file ($(du -h "$file" | cut -f1))"
if [ -n "$minio_file" ]; then echo "screenshots written: $minio_file ($(du -h "$minio_file" | cut -f1))"; fi
