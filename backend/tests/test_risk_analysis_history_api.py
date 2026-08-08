from __future__ import annotations

from typing import Any

from app.repositories.risk_analysis_job_store import RiskAnalysisJobStore


class FakeAsyncResult:
    def __init__(self, state: str, info: dict[str, Any] | None = None) -> None:
        self.state = state
        self.info = info


def _write_submission(
    store: RiskAnalysisJobStore,
    *,
    task_id: str,
    submitted_at: str,
) -> None:
    store.write_json(
        task_id=task_id,
        filename="submission.json",
        payload={
            "task_id": task_id,
            "status": "QUEUED",
            "submitted_at": submitted_at,
            "request": {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[118.9, 32.1]]],
                },
                "weights": [
                    {"code": "PM25", "weight_percent": 30},
                    {"code": "AQI", "weight_percent": 40},
                    {"code": "NDVI", "weight_percent": 30},
                ],
            },
        },
    )


def test_job_store_lists_only_known_task_directories(app):
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    _write_submission(
        store,
        task_id="known-task",
        submitted_at="2026-08-08T01:00:00+00:00",
    )
    unrelated = store.root_dir / "unrelated"
    unrelated.mkdir(parents=True)
    (unrelated / "note.txt").write_text("not a task", encoding="utf-8")
    (store.root_dir / "loose-file.txt").write_text("ignore", encoding="utf-8")

    assert set(store.list_task_ids()) == {"known-task"}


def test_history_endpoint_returns_newest_first_with_compact_request_summary(
    client,
    app,
    monkeypatch,
):
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    _write_submission(
        store,
        task_id="older-task",
        submitted_at="2026-08-08T01:00:00+00:00",
    )
    _write_submission(
        store,
        task_id="newer-task",
        submitted_at="2026-08-08T02:00:00+00:00",
    )
    store.write_json(
        task_id="newer-task",
        filename="result.json",
        payload={"task_id": "newer-task", "status": "SUCCEEDED"},
    )
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.AsyncResult",
        lambda _: FakeAsyncResult("PENDING"),
    )

    response = client.get("/api/v1/risk-analysis/jobs?limit=20")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total"] == 2
    assert [item["task_id"] for item in payload["items"]] == [
        "newer-task",
        "older-task",
    ]
    assert payload["items"][0]["status"] == "SUCCEEDED"
    assert payload["items"][1]["status"] == "QUEUED"
    assert payload["items"][0]["request_summary"]["geometry_type"] == "Polygon"
    assert payload["items"][0]["request_summary"]["weights"][0]["code"] == "PM25"
    assert "geometry" not in payload["items"][0]["request_summary"]


def test_history_endpoint_respects_limit(client, app, monkeypatch):
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    for index in range(3):
        _write_submission(
            store,
            task_id=f"task-{index}",
            submitted_at=f"2026-08-08T0{index + 1}:00:00+00:00",
        )
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.AsyncResult",
        lambda _: FakeAsyncResult("PENDING"),
    )

    response = client.get("/api/v1/risk-analysis/jobs?limit=2")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total"] == 3
    assert len(payload["items"]) == 2


def test_history_endpoint_rejects_invalid_limit(client):
    response = client.get("/api/v1/risk-analysis/jobs?limit=0")

    assert response.status_code == 422
    assert response.get_json()["code"] == "INVALID_REQUEST"
