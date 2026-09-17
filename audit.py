"""
audit.py
Writes tamper-evident audit log entries. Every function that changes
students/expenses/handovers/users should call write_audit_log() in the
SAME database transaction as the actual change (don't commit separately -
pass the same `db` session and let the caller's commit cover both writes).
"""
import hashlib
import json
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from schema_v2 import AuditLog

GENESIS_HASH = "0" * 64


def _serialize(value: Optional[dict]) -> str:
    if value is None:
        return "null"
    return json.dumps(value, sort_keys=True, default=str)  # default=str handles datetimes etc.


def _compute_entry_hash(prev_hash: str, timestamp: datetime, user_id: Optional[int],
                         action: str, table_name: str, record_id: int,
                         old_value: Optional[dict], new_value: Optional[dict]) -> str:
    content = "|".join([
        prev_hash,
        timestamp.isoformat(),
        str(user_id),
        action,
        table_name,
        str(record_id),
        _serialize(old_value),
        _serialize(new_value),
    ])
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def write_audit_log(
    db: Session,
    *,
    user_id: Optional[int],
    action: str,
    table_name: str,
    record_id: int,
    old_value: Optional[dict] = None,
    new_value: Optional[dict] = None,
) -> AuditLog:
    """
    Appends one hash-chained audit row. Does NOT call db.commit() - the
    caller commits this alongside the real change so both succeed or both
    roll back together.
    """
    last_entry = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
    prev_hash = last_entry.entry_hash if last_entry else GENESIS_HASH

    timestamp = datetime.utcnow()
    entry_hash = _compute_entry_hash(
        prev_hash, timestamp, user_id, action, table_name, record_id, old_value, new_value
    )

    entry = AuditLog(
        timestamp=timestamp,
        user_id=user_id,
        action=action,
        table_name=table_name,
        record_id=record_id,
        old_value=old_value,
        new_value=new_value,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
    )
    db.add(entry)
    return entry


def verify_chain_integrity(db: Session) -> tuple[bool, Optional[int]]:
    """
    Walks the entire audit_log table in order and recomputes each hash.
    Returns (True, None) if the chain is intact, or (False, entry_id) for
    the first row where the recomputed hash doesn't match - that's the
    point of tampering (or corruption).
    """
    entries = db.query(AuditLog).order_by(AuditLog.id.asc()).all()
    prev_hash = GENESIS_HASH
    for entry in entries:
        expected = _compute_entry_hash(
            prev_hash, entry.timestamp, entry.user_id, entry.action,
            entry.table_name, entry.record_id, entry.old_value, entry.new_value,
        )
        if expected != entry.entry_hash or entry.prev_hash != prev_hash:
            return False, entry.id
        prev_hash = entry.entry_hash
    return True, None
