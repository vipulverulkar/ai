#!/bin/sh
# Fix ownership of the persistent data directory, then drop to appuser.
# This makes both named volumes and host bind-mounts work out of the box.
set -eu

DB_FILE="${EXPENSE_DB:-/data/expenses.db}"
# dirname fallback for values without a slash
case "$DB_FILE" in
  */*) DB_DIR=$(dirname "$DB_FILE") ;;
  *) DB_DIR="." ;;
esac

mkdir -p "$DB_DIR" /data
# chown may fail on read-only mounts — don't block startup then.
chown -R appuser:appuser "$DB_DIR" /data 2>/dev/null || true
if [ -e "$DB_FILE" ]; then
  chown appuser:appuser "$DB_FILE" "$DB_FILE-wal" "$DB_FILE-journal" "$DB_FILE-shm" 2>/dev/null || true
fi

exec runuser -u appuser -- "$@"
