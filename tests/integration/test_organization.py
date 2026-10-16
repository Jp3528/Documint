import logging
import os
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dependencies import get_session
from apps.api.main import create_app
from packages.config import Settings
from packages.identity.models import Department, DepartmentMember, User, UserRole
from packages.identity.organization import load_actor
from packages.identity.policies import DocumentScope, RoleName, can_read_document
from packages.identity.security import TokenCodec, hash_password

pytestmark = [
    pytest.mark.infrastructure,
    pytest.mark.skipif(
        os.getenv("DOCUMIND_TEST_INFRA") != "1", reason="requires PostgreSQL infrastructure"
    ),
]


@dataclass
class OrganizationHarness:
    client: TestClient
    factory: sessionmaker[Session]
    settings: Settings
    passwords: dict[RoleName, str]
    user_ids: dict[RoleName, UUID]
    department_ids: tuple[UUID, UUID]

    def login(self, role: RoleName) -> dict[str, str]:
        response = self.client.post(
            "/auth/login",
            headers={"X-DocuMind-CSRF": "1"},
            json={
                "email": f"{role.value.lower()}@documind.example",
                "password": self.passwords[role],
            },
        )
        assert response.status_code == 200
        return {"Authorization": "Bearer " + response.json()["access_token"]}


@pytest.fixture
def organization(isolated_db: sessionmaker[Session]) -> Iterator[OrganizationHarness]:
    ids: dict[RoleName, UUID] = {}
    passwords = {role: secrets.token_urlsafe(24) for role in RoleName}
    departments = (uuid4(), uuid4())
    with isolated_db() as db:
        db.add_all(
            [
                Department(id=departments[0], code="ENGINEERING", name="Engineering"),
                Department(id=departments[1], code="PEOPLE", name="People"),
            ]
        )
        for role in RoleName:
            user = User(
                email=f"{role.value.lower()}@documind.example",
                display_name=role.value,
                password_hash=hash_password(passwords[role]),
            )
            db.add(user)
            db.flush()
            ids[role] = user.id
            db.add(UserRole(user_id=user.id, role_name=role.value))
        db.add(DepartmentMember(user_id=ids[RoleName.EMPLOYEE], department_id=departments[0]))
        db.commit()

    def override_session() -> Iterator[Session]:
        with isolated_db() as db:
            yield db

    settings = Settings(auth_secret=SecretStr(secrets.token_urlsafe(48)))
    app = create_app(settings)
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield OrganizationHarness(client, isolated_db, settings, passwords, ids, departments)


@pytest.mark.parametrize("role", [RoleName.EMPLOYEE, RoleName.KNOWLEDGE_MANAGER, RoleName.AUDITOR])
def test_non_admin_cannot_list_users_assign_roles_or_mutate_departments(
    organization: OrganizationHarness,
    role: RoleName,
) -> None:
    h = organization
    headers = h.login(role)
    assert h.client.get("/admin/users", headers=headers).status_code == 403
    assert h.client.get("/admin/roles", headers=headers).status_code == 403
    assert (
        h.client.put(
            f"/admin/users/{h.user_ids[role]}/roles", headers=headers, json={"roles": ["ADMIN"]}
        ).status_code
        == 403
    )
    assert (
        h.client.post(
            "/departments", headers=headers, json={"code": "OTHER", "name": "Other"}
        ).status_code
        == 403
    )
    assert (
        h.client.post(
            f"/departments/{h.department_ids[1]}/memberships",
            headers=headers,
            json={"user_id": str(h.user_ids[role])},
        ).status_code
        == 403
    )
    for method, path, payload in (
        ("GET", f"/admin/users/{h.user_ids[RoleName.ADMIN]}", None),
        (
            "POST",
            "/admin/users",
            {
                "email": "escalation@documind.example",
                "display_name": "Escalation attempt",
                "password": secrets.token_urlsafe(24),
                "roles": ["ADMIN"],
            },
        ),
        ("PATCH", f"/admin/users/{h.user_ids[RoleName.ADMIN]}", {"status": "INACTIVE"}),
        ("PATCH", f"/departments/{h.department_ids[0]}", {"active": False}),
        ("GET", f"/departments/{h.department_ids[0]}/memberships", None),
        (
            "DELETE",
            f"/departments/{h.department_ids[0]}/memberships/{h.user_ids[role]}",
            None,
        ),
    ):
        assert h.client.request(method, path, headers=headers, json=payload).status_code == 403


def test_every_identity_endpoint_rejects_anonymous_requests(
    organization: OrganizationHarness,
) -> None:
    h = organization
    user, department = h.user_ids[RoleName.ADMIN], h.department_ids[0]
    for method, path in (
        ("GET", "/me"),
        ("GET", "/admin/users"),
        ("POST", "/admin/users"),
        ("GET", f"/admin/users/{user}"),
        ("PATCH", f"/admin/users/{user}"),
        ("PUT", f"/admin/users/{user}/roles"),
        ("GET", "/admin/roles"),
        ("GET", "/departments"),
        ("POST", "/departments"),
        ("GET", f"/departments/{department}"),
        ("PATCH", f"/departments/{department}"),
        ("GET", f"/departments/{department}/memberships"),
        ("POST", f"/departments/{department}/memberships"),
        ("DELETE", f"/departments/{department}/memberships/{user}"),
    ):
        assert h.client.request(method, path).status_code == 401


def test_signed_privilege_claims_and_other_identity_cannot_override_database(
    organization: OrganizationHarness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    h = organization
    headers = h.login(RoleName.EMPLOYEE)
    codec = TokenCodec(h.settings)
    payload = codec.decode(headers["Authorization"].removeprefix("Bearer ")).model_dump(mode="json")
    assert h.settings.auth_secret is not None
    key = h.settings.auth_secret.get_secret_value()
    payload.update(roles=["ADMIN"], departments=[str(h.department_ids[1])])
    forged = jwt.encode(payload, key, algorithm="HS256")
    forged_headers = {"Authorization": "Bearer " + forged}
    assert h.client.get("/admin/users", headers=forged_headers).status_code == 403
    own = h.client.get(f"/me?user_id={h.user_ids[RoleName.ADMIN]}", headers=forged_headers)
    assert own.status_code == 200 and own.json()["id"] == str(h.user_ids[RoleName.EMPLOYEE])
    assert own.json()["roles"] == ["EMPLOYEE"]
    assert [item["id"] for item in own.json()["departments"]] == [str(h.department_ids[0])]
    payload["sub"] = str(h.user_ids[RoleName.ADMIN])
    mismatched = jwt.encode(payload, key, algorithm="HS256")
    assert h.client.get("/me", headers={"Authorization": "Bearer " + mismatched}).status_code == 401
    assert all(value not in caplog.text for value in [forged, mismatched, *h.passwords.values()])


def test_employee_sees_only_membership_and_foreign_ids_match_missing(
    organization: OrganizationHarness,
) -> None:
    h = organization
    headers = h.login(RoleName.EMPLOYEE)
    listed = h.client.get("/departments", headers=headers)
    assert listed.status_code == 200 and listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == str(h.department_ids[0])
    foreign = h.client.get(f"/departments/{h.department_ids[1]}", headers=headers)
    missing = h.client.get(f"/departments/{uuid4()}", headers=headers)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert (
        h.client.get(f"/admin/users/{h.user_ids[RoleName.ADMIN]}", headers=headers).status_code
        == 403
    )


def test_admin_crud_pagination_validation_and_unique_membership(
    organization: OrganizationHarness,
) -> None:
    h = organization
    headers = h.login(RoleName.ADMIN)
    page = h.client.get("/admin/users?limit=2&offset=1", headers=headers)
    assert page.status_code == 200 and len(page.json()["items"]) == 2 and page.json()["total"] == 4
    assert "password" not in page.text
    assert h.client.get("/admin/users?limit=101", headers=headers).status_code == 422
    assert h.client.get("/admin/users?offset=-1", headers=headers).status_code == 422
    payload = {
        "email": " NEW@DOCUMIND.EXAMPLE ",
        "display_name": "New person",
        "password": secrets.token_urlsafe(24),
        "roles": ["EMPLOYEE"],
    }
    created = h.client.post("/admin/users", headers=headers, json=payload)
    assert created.status_code == 201 and created.json()["email"] == "new@documind.example"
    assert h.client.post("/admin/users", headers=headers, json=payload).status_code == 409
    assert (
        h.client.post(
            "/admin/users", headers=headers, json={**payload, "roles": ["ADMIN", "ADMIN"]}
        ).status_code
        == 422
    )
    department = h.client.post(
        "/departments", headers=headers, json={"code": " finance ", "name": "Finance"}
    )
    assert department.status_code == 201 and department.json()["code"] == "FINANCE"
    department_id = department.json()["id"]
    member = {"user_id": created.json()["id"], "membership_role": "MEMBER"}
    path = f"/departments/{department_id}/memberships"
    assert h.client.post(path, headers=headers, json=member).status_code == 201
    assert h.client.post(path, headers=headers, json=member).status_code == 409
    assert h.client.get(path + "?limit=1", headers=headers).json()["total"] == 1
    assert h.client.delete(path + "/" + member["user_id"], headers=headers).status_code == 204


def test_permissions_refresh_without_new_login(organization: OrganizationHarness) -> None:
    h = organization
    employee_headers = h.login(RoleName.EMPLOYEE)
    admin_headers = h.login(RoleName.ADMIN)
    employee_id = h.user_ids[RoleName.EMPLOYEE]
    department_id = h.department_ids[0]
    with h.factory() as db:
        user = db.get(User, employee_id)
        assert user
        resource = DocumentScope(uuid4(), department_id, "DEPARTMENT")
        assert can_read_document(load_actor(db, user), resource)
    response = h.client.delete(
        f"/departments/{department_id}/memberships/{employee_id}", headers=admin_headers
    )
    assert response.status_code == 204
    assert h.client.get("/departments", headers=employee_headers).json()["total"] == 0
    with h.factory() as db:
        user = db.get(User, employee_id)
        assert user and not can_read_document(load_actor(db, user), resource)
    profile = h.client.get("/me", headers=employee_headers).json()
    assert profile["roles"] == ["EMPLOYEE"] and not profile["capabilities"]["manage_users"]
    assert (
        h.client.put(
            f"/admin/users/{employee_id}/roles", headers=admin_headers, json={"roles": ["ADMIN"]}
        ).status_code
        == 200
    )
    assert h.client.get("/admin/users", headers=employee_headers).status_code == 200
    assert (
        h.client.put(
            f"/admin/users/{employee_id}/roles", headers=admin_headers, json={"roles": ["EMPLOYEE"]}
        ).status_code
        == 200
    )
    assert h.client.get("/admin/users", headers=employee_headers).status_code == 403


def test_last_admin_and_deactivation_guards(organization: OrganizationHarness) -> None:
    h = organization
    admin_headers = h.login(RoleName.ADMIN)
    employee_headers = h.login(RoleName.EMPLOYEE)
    admin_id = h.user_ids[RoleName.ADMIN]
    assert (
        h.client.put(
            f"/admin/users/{admin_id}/roles", headers=admin_headers, json={"roles": ["EMPLOYEE"]}
        ).status_code
        == 409
    )
    assert (
        h.client.patch(
            f"/admin/users/{admin_id}", headers=admin_headers, json={"status": "INACTIVE"}
        ).status_code
        == 409
    )
    assert (
        h.client.patch(
            f"/admin/users/{h.user_ids[RoleName.EMPLOYEE]}",
            headers=admin_headers,
            json={"status": "INACTIVE"},
        ).status_code
        == 200
    )
    assert h.client.get("/me", headers=employee_headers).status_code == 401
