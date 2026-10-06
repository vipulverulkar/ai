"""Backup, restore and session inspection (MVC: Controller, admin only)."""
import io
import os
import sqlite3
import time

from flask import Blueprint, jsonify, request, send_file

from app.config import BACKEND_DIR
from app.rbac import require_admin

maintenance_bp = Blueprint('maintenance', __name__)

DB_PATH = os.path.join(BACKEND_DIR, 'clinic.db')
SESSIONS_DB = os.environ.get(
    'SESSIONS_DB', os.path.join(BACKEND_DIR, '..', 'frontend', 'sessions.db'))
REQUIRED_TABLES = {'patient', 'doctor', 'treatment', 'appointment', 'user',
                   'bill', 'lookup'}


@maintenance_bp.route('/api/backup', methods=['GET'])
@require_admin
def backup():
    buf = io.BytesIO()
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(':memory:')
    try:
        with dst:
            src.backup(dst)
        for line in dst.iterdump():
            buf.write((line + '\n').encode('utf-8'))
    finally:
        dst.close()
        src.close()
    buf.seek(0)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    return send_file(buf, mimetype='application/sql',
                     as_attachment=True, download_name=f'clinic-backup-{stamp}.sql')


@maintenance_bp.route('/api/restore', methods=['POST'])
@require_admin
def restore():
    f = request.files.get('backup')
    if f is None:
        return jsonify({'error': 'No backup file uploaded'}), 400
    head = f.stream.read(64)
    f.stream.seek(0)
    sniff = f.stream.read(4096).decode('utf-8', errors='ignore')
    f.stream.seek(0)
    text_head = sniff
    is_sqlite = head[:16] == b'SQLite format 3\x00'
    is_dump = 'CREATE TABLE' in text_head and 'clinic' in text_head.lower()
    if not (is_sqlite or is_dump):
        return jsonify({'error': 'File is not a recognized clinic backup'}), 400
    if is_sqlite:
        tmp = DB_PATH + '.upload'
        f.save(tmp)
        try:
            con = sqlite3.connect(tmp)
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            con.close()
        except sqlite3.DatabaseError:
            os.remove(tmp)
            return jsonify({'error': 'Corrupt SQLite file'}), 400
        if not REQUIRED_TABLES.issubset(tables):
            os.remove(tmp)
            return jsonify({'error': 'Backup is missing clinic tables'}), 400
        os.replace(tmp, DB_PATH)
    else:
        try:
            body = f.stream.read().decode('utf-8', errors='ignore')
        except UnicodeError as e:
            return jsonify({'error': f'Restore failed: {e}'}), 400
        tmp = DB_PATH + '.restore'
        if os.path.exists(tmp):
            os.remove(tmp)
        con = sqlite3.connect(tmp)
        try:
            con.executescript(body)
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not REQUIRED_TABLES.issubset(tables):
                return jsonify({'error': 'Backup is missing clinic tables'}), 400
            con.commit()
        except sqlite3.DatabaseError as e:
            return jsonify({'error': f'Restore failed: {e}'}), 400
        finally:
            con.close()
        os.replace(tmp, DB_PATH)
        # Drop pooled connections holding the old (replaced) file handle
        from app.models import db as _db
        _db.session.remove()
        _db.engine.dispose()
    return jsonify({'status': 'restored',
                    'note': 'Restart the backend if data looks stale in open sessions'})


@maintenance_bp.route('/api/sessions', methods=['GET'])
@require_admin
def list_sessions():
    if not os.path.exists(SESSIONS_DB):
        return jsonify([])
    con = sqlite3.connect(SESSIONS_DB)
    try:
        rows = con.execute(
            'SELECT sid, sess, expired FROM sessions').fetchall()
    except sqlite3.DatabaseError:
        return jsonify([])
    finally:
        con.close()
    now_ms = int(time.time() * 1000)
    out = []
    for sid, sess, expired in rows:
        if expired and expired < now_ms:
            continue
        try:
            import json as _json
            username = _json.loads(sess).get('user', {}).get('username')
        except (ValueError, AttributeError):
            username = None
        out.append({'sid': sid, 'short': sid[:8],
                    'username': username or 'anonymous',
                    'expires': expired})
    return jsonify(out)


@maintenance_bp.route('/api/sessions/<sid>', methods=['DELETE'])
@require_admin
def revoke_session(sid):
    if not os.path.exists(SESSIONS_DB):
        return jsonify({'error': 'No session store'}), 404
    con = sqlite3.connect(SESSIONS_DB)
    try:
        cur = con.execute('DELETE FROM sessions WHERE sid = ?', (sid,))
        con.commit()
        if cur.rowcount == 0:
            return jsonify({'error': 'Session not found'}), 404
    finally:
        con.close()
    return '', 204
