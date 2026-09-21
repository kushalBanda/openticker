"""Recent audit log entries, most recent first."""

from openticker.storage.sqlite.audit_repo import AuditEntry, list_audit


def get_audit_log(limit: int, event_type: str | None) -> list[AuditEntry]:
    return list_audit(limit, event_type)
