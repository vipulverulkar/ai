"""Automatic audit trail (MVC: service). Logs every DB write with the actor
taken from the X-User request header. Skipped outside request context
(e.g. startup seeding) and never logs AuditLog rows themselves."""
from flask import g, has_request_context
from sqlalchemy import event
from sqlalchemy.orm import Mapper

from app.models import db
from app.models.setting import AuditLog


def _actor():
    if has_request_context():
        return getattr(g, 'actor', None) or 'system'
    return None


def _describe(target):
    for attr in ('username', 'name', 'value', 'bill_no'):
        val = getattr(target, attr, None)
        if val:
            return str(val)[:120]
    return ''


def _record(connection, action, target):
    actor = _actor()
    if actor is None or isinstance(target, AuditLog):
        return
    entity_id = getattr(target, 'id', None) or getattr(target, 'key', None)
    connection.execute(
        AuditLog.__table__.insert().values(
            actor=actor,
            action=action,
            entity=target.__class__.__name__.lower(),
            entity_id=str(entity_id) if entity_id is not None else None,
            detail=_describe(target),
        )
    )


def log_action(action, entity, entity_id=None, detail=''):
    """Manual audit entry for events without a DB write (e.g. logins)."""
    actor = _actor()
    if actor is None:
        return
    db.session.add(AuditLog(actor=actor, action=action, entity=entity,
                            entity_id=str(entity_id) if entity_id is not None else None,
                            detail=detail[:300] if detail else ''))
    db.session.commit()


def init_audit():
    event.listen(Mapper, 'after_insert', lambda m, c, t: _record(c, 'create', t))
    event.listen(Mapper, 'after_update', lambda m, c, t: _record(c, 'update', t))
    event.listen(Mapper, 'after_delete', lambda m, c, t: _record(c, 'delete', t))
