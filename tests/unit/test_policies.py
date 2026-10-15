from dataclasses import replace
from uuid import uuid4

import pytest

from packages.identity.policies import (
    Action,
    Actor,
    DocumentScope,
    RoleName,
    can_read_document,
    can_view_department,
    permits,
)


@pytest.mark.parametrize("role", list(RoleName))
@pytest.mark.parametrize("action", list(Action))
def test_role_action_matrix(role: RoleName, action: Action) -> None:
    actor = Actor(uuid4(), True, frozenset({role}))
    expected = (
        role == RoleName.ADMIN
        or (role == RoleName.AUDITOR and action == Action.VIEW_AUDIT)
        or (role == RoleName.KNOWLEDGE_MANAGER and action == Action.MANAGE_KNOWLEDGE)
    )
    assert permits(actor, action) is expected
    assert not permits(replace(actor, active=False), action)


def test_document_scope_denies_inactive_auditor_and_unrelated_department() -> None:
    department_id = uuid4()
    employee = Actor(uuid4(), True, frozenset({RoleName.EMPLOYEE}), frozenset({department_id}))
    document = DocumentScope(uuid4(), department_id, "DEPARTMENT")
    assert can_read_document(employee, document)
    assert not can_read_document(replace(employee, departments=frozenset()), document)
    assert not can_read_document(replace(employee, active=False), document)
    auditor = replace(employee, roles=frozenset({RoleName.AUDITOR}))
    assert not can_read_document(auditor, replace(document, visibility="COMPANY"))
    assert can_read_document(
        auditor, replace(document, visibility="RESTRICTED", read_users=frozenset({auditor.id}))
    )
    assert not can_read_document(employee, replace(document, visibility="RESTRICTED"))
    assert can_read_document(
        employee, replace(document, visibility="RESTRICTED", owner_id=employee.id)
    )


def test_department_visibility_and_unknown_action_fail_closed() -> None:
    department_id = uuid4()
    employee = Actor(uuid4(), True, frozenset({RoleName.EMPLOYEE}), frozenset({department_id}))
    assert can_view_department(employee, department_id)
    assert not can_view_department(employee, uuid4())
    assert not can_view_department(employee, department_id, active=False)
    assert not permits(employee, Action.MANAGE_USERS)
