import pytest
from flask_jwt_extended import create_access_token

from app.extensions import db
from app.models import User


def test_register_login_refresh_me_and_logout(app, anonymous_client):
    register = anonymous_client.post(
        "/api/v1/auth/register",
        json={"username": "new-user", "password": "strong-password"},
    )
    assert register.status_code == 201
    assert register.get_json()["access_token"]
    assert "HttpOnly" in register.headers["Set-Cookie"]
    assert "SameSite=Lax" in register.headers["Set-Cookie"]

    login = anonymous_client.post(
        "/api/v1/auth/login",
        json={"username": "new-user", "password": "strong-password"},
    )
    access_token = login.get_json()["access_token"]
    me = anonymous_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert me.status_code == 200
    assert me.get_json()["user"]["username"] == "new-user"

    assert anonymous_client.post("/api/v1/auth/refresh").status_code == 200
    assert anonymous_client.post("/api/v1/auth/logout").status_code == 200
    assert app.extensions["redis_auth"].values
    assert anonymous_client.post("/api/v1/auth/refresh").status_code == 401


def test_registration_can_be_disabled(app, anonymous_client):
    app.config["REGISTRATION_ENABLED"] = False

    response = anonymous_client.post(
        "/api/v1/auth/register",
        json={"username": "closed-user", "password": "strong-password"},
    )

    assert response.status_code == 403
    assert response.get_json()["code"] == "REGISTRATION_DISABLED"


def test_login_rejects_invalid_credentials(anonymous_client):
    response = anonymous_client.post(
        "/api/v1/auth/login",
        json={"username": "test-user", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.get_json()["code"] == "INVALID_CREDENTIALS"


def test_risk_jobs_require_authentication(anonymous_client):
    response = anonymous_client.get("/api/v1/risk-analysis/jobs")

    assert response.status_code == 401


@pytest.mark.parametrize(
    "suffix",
    [
        "",
        "/submission",
        "/result",
        "/result/artifacts/manifest",
        "/result/artifacts/raster",
        "/result/artifacts/preview",
        "/result/spatial",
    ],
)
def test_risk_job_is_hidden_from_another_user(
    app, client, monkeypatch, suffix
):
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        lambda *args, **kwargs: object(),
    )
    created = client.post(
        "/api/v1/risk-analysis/jobs",
        headers={"Idempotency-Key": "owner-test-key"},
        json={
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [118.9, 32.1],
                        [118.91, 32.1],
                        [118.91, 32.11],
                        [118.9, 32.11],
                        [118.9, 32.1],
                    ]
                ],
            },
            "weights": [{"code": "PM25", "weight_percent": 100}],
        },
    )
    task_id = created.get_json()["task_id"]

    with app.app_context():
        other = User(username="other-user")
        other.set_password("other-password")
        db.session.add(other)
        db.session.commit()
        other_token = create_access_token(identity=str(other.id))

    response = client.get(
        f"/api/v1/risk-analysis/jobs/{task_id}{suffix}",
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert response.status_code == 404


def test_refresh_cookie_requires_csrf_in_production(app, anonymous_client):
    app.config.update(JWT_COOKIE_CSRF_PROTECT=True, JWT_COOKIE_SECURE=True)
    login = anonymous_client.post(
        "/api/v1/auth/login",
        json={"username": "test-user", "password": "test-password"},
        base_url="https://localhost",
    )

    assert login.status_code == 200
    cookie_headers = login.headers.getlist("Set-Cookie")
    assert any(
        "refresh_token_cookie=" in header
        and "Secure" in header
        and "HttpOnly" in header
        and "SameSite=Lax" in header
        for header in cookie_headers
    )
    assert (
        anonymous_client.post(
            "/api/v1/auth/refresh", base_url="https://localhost"
        ).status_code
        == 401
    )

    csrf_header = next(
        header
        for header in cookie_headers
        if header.startswith("csrf_refresh_token=")
    )
    csrf_token = csrf_header.split(";", 1)[0].split("=", 1)[1]
    refreshed = anonymous_client.post(
        "/api/v1/auth/refresh",
        headers={"X-CSRF-TOKEN": csrf_token},
        base_url="https://localhost",
    )

    assert refreshed.status_code == 200
    assert refreshed.get_json()["access_token"]
