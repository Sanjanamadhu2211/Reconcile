import uuid
from unittest.mock import Mock

import pytest

from app.audit import record
from app.models import AuditEvent, User


def _record(db, **overrides):
    params = {
        "organization_id": uuid.uuid4(),
        "actor": None,
        "action": "import.created",
        "target_type": "import_batch",
        "target_id": uuid.uuid4(),
        **overrides,
    }
    return record(db, **params)


def test_unknown_action_is_rejected_before_the_session_is_touched():
    db = Mock()

    with pytest.raises(ValueError, match="unknown audit action"):
        _record(db, action="import.deleted")

    db.add.assert_not_called()
    db.flush.assert_not_called()


def test_unknown_target_type_is_rejected_before_the_session_is_touched():
    db = Mock()

    with pytest.raises(ValueError, match="unknown audit target type"):
        _record(db, target_type="user")

    db.add.assert_not_called()


def test_system_event_has_no_actor_and_a_system_email():
    db = Mock()

    event = _record(db)

    assert isinstance(event, AuditEvent)
    assert event.actor_user_id is None
    assert event.actor_email == "system"
    assert event.event_metadata == {}
    db.add.assert_called_once_with(event)
    db.flush.assert_called_once()


def test_actor_id_and_email_are_copied_from_the_user():
    db = Mock()
    actor = User(id=uuid.uuid4(), email="reviewer@example.com", password_hash="hash")

    event = _record(db, actor=actor, action="exception.approved", target_type="exception")

    assert event.actor_user_id == actor.id
    assert event.actor_email == "reviewer@example.com"
