"""Maintenance jobs — automatic SQL-dump backups with rotation."""
import os
from datetime import datetime

from .db import connect


def run_backup(config, keep=None):
    """Write a full SQL-dump snapshot to config["BACKUP_DIR"], keep newest N.

    Returns the backup file path. Raises on failure (callers decide whether
    that is fatal — create_app only logs a warning).
    """
    from .modules.data.models import export_sql_backup

    backup_dir = config.get("BACKUP_DIR") or os.path.join(
        os.path.dirname(config.get("EXPENSE_DB") or "."), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    conn = connect(config)
    try:
        body = export_sql_backup(conn)
    finally:
        conn.close()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(backup_dir, f"auto-backup-{stamp}.sql")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, path)
    _rotate(backup_dir, keep if keep is not None else config.get("BACKUP_KEEP", 10))
    return path


def _rotate(backup_dir, keep):
    try:
        keep = max(1, int(keep or 1))
    except (ValueError, TypeError):
        keep = 10
    files = sorted(
        (f for f in os.listdir(backup_dir)
         if f.startswith("auto-backup-") and (f.endswith(".sql") or f.endswith(".json"))),
        reverse=True)
    for old in files[keep:]:
        try:
            os.remove(os.path.join(backup_dir, old))
        except OSError:
            pass
