from datetime import UTC, datetime, timedelta

import pytest

from app.extensions import db
from app.models import AnalysisArtifact, AnalysisJob
from app.repositories.risk_analysis_job_store import RiskAnalysisJobStore


def _request_payload():
    return {
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
    }


def _add_job(app, task_id: str, queued_at: datetime, owner_id: int = 1):
    payload = _request_payload()
    with app.app_context():
        db.session.add(
            AnalysisJob(
                id=task_id,
                owner_id=owner_id,
                idempotency_key=f"{task_id}-key",
                status="QUEUED",
                stage="QUEUED",
                progress=0,
                request_payload=payload,
                geometry=payload["geometry"],
                queued_at=queued_at,
            )
        )
        db.session.commit()


def test_history_uses_database_and_ignores_old_file_jobs(client, app):
    now = datetime.now(UTC)
    _add_job(app, "older-task", now - timedelta(minutes=1))
    _add_job(app, "newer-task", now)
    _add_job(app, "another-users-task", now + timedelta(minutes=1), owner_id=2)
    RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"]).record_submission(
        task_id="legacy-file-task", request_payload=_request_payload()
    )

    response = client.get("/api/v1/risk-analysis/jobs?limit=20")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total"] == 2
    assert [item["task_id"] for item in payload["items"]] == [
        "newer-task",
        "older-task",
    ]
    assert set(payload) == {"items", "limit", "offset", "total"}
    first_item = payload["items"][0]
    assert set(first_item) == {
        "task_id",
        "status",
        "stage",
        "progress",
        "result_available",
        "submitted_at",
        "queued_at",
        "started_at",
        "completed_at",
        "expires_at",
        "parent_job_id",
        "timing",
        "request_summary",
    }
    assert first_item["request_summary"] == {
        "geometry_type": "Polygon",
        "weights": [{"code": "PM25", "weight_percent": 100}],
    }
    assert "geometry" not in first_item["request_summary"]


def test_history_respects_limit_and_offset(client, app):
    now = datetime.now(UTC)
    for index in range(4):
        _add_job(app, f"task-{index}", now + timedelta(minutes=index))

    response = client.get("/api/v1/risk-analysis/jobs?limit=2&offset=1")

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["total"] == 4
    assert [item["task_id"] for item in payload["items"]] == ["task-2", "task-1"]


def test_history_uses_database_status_over_stale_file_result(client, app):
    _add_job(app, "queued-task", datetime.now(UTC))
    RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"]).write_json(
        task_id="queued-task",
        filename="result.json",
        payload={"task_id": "queued-task", "status": "SUCCEEDED"},
    )

    response = client.get("/api/v1/risk-analysis/jobs")

    assert response.status_code == 200
    item = response.get_json()["items"][0]
    assert item["status"] == "QUEUED"
    assert item["result_available"] is False


def test_history_uses_artifact_metadata_without_reading_manifest(
    client, app, monkeypatch
):
    _add_job(app, "metadata-only-task", datetime.now(UTC))
    with app.app_context():
        job = db.session.get(AnalysisJob, "metadata-only-task")
        job.status = "SUCCEEDED"
        job.stage = "COMPLETED"
        db.session.add(
            AnalysisArtifact(
                job_id=job.id,
                kind="manifest",
                relative_path=f"risk-analysis/{job.id}/result.json",
                size_bytes=100,
            )
        )
        db.session.commit()
    monkeypatch.setattr(
        RiskAnalysisJobStore,
        "read_result",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("history must not read result.json")
        ),
    )

    response = client.get("/api/v1/risk-analysis/jobs")

    assert response.status_code == 200
    assert response.get_json()["items"][0]["result_available"] is True


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_history_rejects_invalid_pagination(client, query):
    response = client.get(f"/api/v1/risk-analysis/jobs?{query}")

    assert response.status_code == 422
    assert response.get_json()["code"] == "INVALID_REQUEST"
