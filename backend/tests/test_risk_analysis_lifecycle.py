from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Lock, local

from flask_jwt_extended import create_access_token
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import AnalysisArtifact, AnalysisJob
from app.repositories.analysis_jobs import claim_job
from app.services.job_maintenance import claim_expired_jobs, cleanup_expired_results
from app.tasks.maintenance import reconcile_pending_dispatches


def _payload():
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


def _post(client, key: str):
    return client.post(
        "/api/v1/risk-analysis/jobs",
        json=_payload(),
        headers={"Idempotency-Key": key},
    )


def _add_expired_manifest(app, task_id: str, now: datetime) -> Path:
    path = (
        app.config["RUNTIME_DATA_DIR"]
        / "risk-analysis"
        / task_id
        / "result.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    with app.app_context():
        db.session.add(
            AnalysisJob(
                id=task_id,
                owner_id=1,
                idempotency_key=f"{task_id}-key",
                status="SUCCEEDED",
                stage="COMPLETED",
                progress=100,
                request_payload=_payload(),
                geometry=_payload()["geometry"],
                expires_at=now - timedelta(seconds=1),
            )
        )
        db.session.add(
            AnalysisArtifact(
                job_id=task_id,
                kind="manifest",
                relative_path=f"risk-analysis/{task_id}/result.json",
                size_bytes=2,
                expires_at=now - timedelta(seconds=1),
            )
        )
        db.session.commit()
    return path


def test_missing_idempotency_key_is_rejected_before_enqueue(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        lambda *args, **kwargs: sent.append(kwargs),
    )

    response = client.post("/api/v1/risk-analysis/jobs", json=_payload())

    assert response.status_code == 422
    assert response.get_json()["code"] == "INVALID_IDEMPOTENCY_KEY"
    assert sent == []


def test_idempotency_replay_precedes_rate_and_active_limits(
    client, app, monkeypatch
):
    sent = []
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        lambda *args, **kwargs: sent.append(kwargs["task_id"]),
    )
    first = _post(client, "stable-key")
    app.config["MAX_ACTIVE_JOBS_PER_USER"] = 0
    app.config["SUBMISSION_RATE_LIMIT_PER_MINUTE"] = 0

    replay = _post(client, "stable-key")

    assert first.status_code == 202
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.get_json()["task_id"] == first.get_json()["task_id"]
    assert len(sent) == 1


def test_same_key_with_different_payload_returns_conflict(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        lambda *args, **kwargs: object(),
    )
    assert _post(client, "conflicting-key").status_code == 202
    changed_payload = _payload()
    changed_payload["weights"] = [{"code": "AQI", "weight_percent": 100}]

    response = client.post(
        "/api/v1/risk-analysis/jobs",
        json=changed_payload,
        headers={"Idempotency-Key": "conflicting-key"},
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_concurrent_same_key_returns_one_database_job(app, monkeypatch):
    initial_miss_barrier = Barrier(2)
    simulated_user_row_lock = Lock()
    thread_state = local()
    sent = []
    real_scalar = db.session.scalar
    real_commit = db.session.commit
    real_rollback = db.session.rollback

    def release_user_lock():
        if getattr(thread_state, "owns_user_lock", False):
            thread_state.owns_user_lock = False
            simulated_user_row_lock.release()

    def synchronized_scalar(statement, *args, **kwargs):
        entity = statement.column_descriptions[0].get("entity")
        if entity is AnalysisJob and not getattr(thread_state, "saw_initial_miss", False):
            thread_state.saw_initial_miss = True
            value = real_scalar(statement, *args, **kwargs)
            assert value is None
            initial_miss_barrier.wait(timeout=5)
            return value
        if (
            entity is not None
            and entity.__name__ == "User"
            and statement._for_update_arg is not None
        ):
            simulated_user_row_lock.acquire()
            thread_state.owns_user_lock = True
        return real_scalar(statement, *args, **kwargs)

    def synchronized_commit():
        try:
            return real_commit()
        finally:
            release_user_lock()

    def synchronized_rollback():
        try:
            return real_rollback()
        finally:
            release_user_lock()

    monkeypatch.setattr(db.session, "scalar", synchronized_scalar)
    monkeypatch.setattr(db.session, "commit", synchronized_commit)
    monkeypatch.setattr(db.session, "rollback", synchronized_rollback)
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        lambda *args, **kwargs: sent.append(kwargs["task_id"]),
    )
    with app.app_context():
        token = create_access_token(identity="1")

    def submit():
        with app.test_client() as concurrent_client:
            return concurrent_client.post(
                "/api/v1/risk-analysis/jobs",
                json=_payload(),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Idempotency-Key": "concurrent-key",
                },
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(submit)
        second_future = executor.submit(submit)
        second = second_future.result(timeout=5)
        first = first_future.result(timeout=5)

    assert {first.status_code, second.status_code} == {200, 202}
    assert first.get_json()["task_id"] == second.get_json()["task_id"]
    assert sent == [first.get_json()["task_id"]]
    assert sum(app.extensions["redis_auth"].counters.values()) == 1
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(AnalysisJob)) == 1


def test_unique_conflict_rolls_back_and_reads_existing_job(
    client, app, monkeypatch
):
    real_commit = db.session.commit
    raised = False

    def committed_conflict():
        nonlocal raised
        real_commit()
        if not raised:
            raised = True
            raise IntegrityError("insert", {}, Exception("unique conflict"))

    monkeypatch.setattr(db.session, "commit", committed_conflict)
    response = _post(client, "conflict-key")

    assert response.status_code == 200
    assert response.headers["Idempotency-Replayed"] == "true"
    with app.app_context():
        jobs = db.session.scalars(db.select(AnalysisJob)).all()
        assert len(jobs) == 1
        assert response.get_json()["task_id"] == jobs[0].id


def test_rate_limit_and_redis_failure_do_not_enqueue_extra_jobs(
    client, app, monkeypatch
):
    sent = []
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        lambda *args, **kwargs: sent.append(kwargs["task_id"]),
    )
    app.config["SUBMISSION_RATE_LIMIT_PER_MINUTE"] = 1

    assert _post(client, "rate-key-1").status_code == 202
    limited = _post(client, "rate-key-2")

    assert limited.status_code == 429
    assert limited.get_json()["code"] == "SUBMISSION_RATE_LIMITED"
    assert int(limited.headers["Retry-After"]) > 0
    assert len(sent) == 1
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(AnalysisJob)) == 1

    app.extensions["redis_auth"].eval = lambda *args: (_ for _ in ()).throw(
        ConnectionError("redis unavailable")
    )
    unavailable = _post(client, "redis-down-key")
    assert unavailable.status_code == 503
    assert unavailable.get_json()["code"] == "RATE_LIMIT_UNAVAILABLE"
    assert len(sent) == 1


def test_active_limit_does_not_enqueue(client, app, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        lambda *args, **kwargs: sent.append(kwargs["task_id"]),
    )
    app.config["MAX_ACTIVE_JOBS_PER_USER"] = 1
    app.config["SUBMISSION_RATE_LIMIT_PER_MINUTE"] = 100

    assert _post(client, "active-key-1").status_code == 202
    limited = _post(client, "active-key-2")

    assert limited.status_code == 429
    assert limited.get_json()["code"] == "ACTIVE_JOB_LIMIT_REACHED"
    assert len(sent) == 1
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(AnalysisJob)) == 1


def test_retry_creates_child_and_cancel_is_safe(client, app, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        lambda *args, **kwargs: object(),
    )
    original = _post(client, "original-key")
    original_id = original.get_json()["task_id"]
    with app.app_context():
        job = db.session.get(AnalysisJob, original_id)
        job.status = "FAILED"
        job.stage = "FAILED"
        job.completed_at = datetime.now(UTC)
        db.session.commit()

    retried = client.post(
        f"/api/v1/risk-analysis/jobs/{original_id}/retry",
        headers={"Idempotency-Key": "retry-key"},
    )

    assert retried.status_code == 202
    child_id = retried.get_json()["task_id"]
    with app.app_context():
        original_job = db.session.get(AnalysisJob, original_id)
        child = db.session.get(AnalysisJob, child_id)
        assert original_job.status == "FAILED"
        assert child.parent_job_id == original_id
        assert child.request_payload == original_job.request_payload

    canceled = client.post(f"/api/v1/risk-analysis/jobs/{child_id}/cancel")
    assert canceled.status_code == 200
    assert canceled.get_json()["status"] == "CANCELED"
    with app.app_context():
        assert claim_job(child_id) is False


def test_running_cancel_is_explicitly_unsupported(client, app, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        lambda *args, **kwargs: object(),
    )
    task_id = _post(client, "running-key").get_json()["task_id"]
    with app.app_context():
        assert claim_job(task_id) is True

    response = client.post(f"/api/v1/risk-analysis/jobs/{task_id}/cancel")

    assert response.status_code == 409
    assert response.get_json()["code"] == "RUNNING_CANCEL_UNSUPPORTED"


def test_cleanup_deletes_registered_files_and_keeps_expired_audit(
    client, app
):
    now = datetime.now(UTC)
    task_id = "expired-job"
    task_dir = app.config["RUNTIME_DATA_DIR"] / "risk-analysis" / task_id
    task_dir.mkdir(parents=True)
    manifest_path = task_dir / "result.json"
    raster_path = task_dir / "risk.tif"
    manifest_path.write_text("{}", encoding="utf-8")
    raster_path.write_bytes(b"raster")
    with app.app_context():
        job = AnalysisJob(
            id=task_id,
            owner_id=1,
            idempotency_key="expired-key",
            status="SUCCEEDED",
            stage="COMPLETED",
            progress=100,
            request_payload=_payload(),
            geometry=_payload()["geometry"],
            queued_at=now - timedelta(minutes=2),
            started_at=now - timedelta(minutes=1),
            completed_at=now - timedelta(seconds=30),
            expires_at=now - timedelta(seconds=1),
        )
        db.session.add(job)
        db.session.add_all(
            [
                AnalysisArtifact(
                    job_id=task_id,
                    kind="manifest",
                    relative_path=f"risk-analysis/{task_id}/result.json",
                    size_bytes=2,
                    expires_at=job.expires_at,
                ),
                AnalysisArtifact(
                    job_id=task_id,
                    kind="raster",
                    relative_path=f"risk-analysis/{task_id}/risk.tif",
                    size_bytes=6,
                    expires_at=job.expires_at,
                ),
            ]
        )
        db.session.commit()

        assert cleanup_expired_results(now) == 1
        db.session.refresh(job)
        assert job.status == "EXPIRED"
        assert all(artifact.deleted_at is not None for artifact in job.artifacts)

    assert not manifest_path.exists()
    assert not raster_path.exists()
    status = client.get(f"/api/v1/risk-analysis/jobs/{task_id}")
    assert status.status_code == 200
    assert status.get_json()["status"] == "EXPIRED"
    assert status.get_json()["timing"] == {
        "queue_seconds": 60.0,
        "execution_seconds": 30.0,
        "total_seconds": 90.0,
    }
    for suffix in (
        "/result",
        "/result/artifacts/manifest",
        "/result/artifacts/preview",
        "/result/spatial",
    ):
        response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}{suffix}")
        assert response.status_code == 410
        assert response.get_json()["code"] == "RESULT_EXPIRED"


def test_expiry_claim_is_atomic_and_precedes_file_deletion(app):
    now = datetime.now(UTC)
    path = _add_expired_manifest(app, "claim-once-job", now)
    with app.app_context():
        assert claim_expired_jobs(now) == ["claim-once-job"]
        assert claim_expired_jobs(now) == []
        assert db.session.get(AnalysisJob, "claim-once-job").status == "EXPIRED"
        assert path.exists()


def test_cleanup_retries_file_deletion_failure(app, monkeypatch):
    now = datetime.now(UTC)
    path = _add_expired_manifest(app, "delete-retry-job", now)
    original_unlink = Path.unlink

    def fail_once(candidate, *args, **kwargs):
        if candidate == path:
            with app.app_context():
                assert db.session.get(AnalysisJob, "delete-retry-job").status == (
                    "EXPIRED"
                )
            raise OSError("storage busy")
        return original_unlink(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_once)
    with app.app_context():
        assert cleanup_expired_results(now) == 1
        artifact = db.session.scalar(
            db.select(AnalysisArtifact).where(
                AnalysisArtifact.job_id == "delete-retry-job"
            )
        )
        assert artifact.deleted_at is None
        assert path.exists()

    monkeypatch.setattr(Path, "unlink", original_unlink)
    with app.app_context():
        assert cleanup_expired_results(now) == 0
        assert db.session.scalar(
            db.select(AnalysisArtifact).where(
                AnalysisArtifact.job_id == "delete-retry-job"
            )
        ).deleted_at is not None
        assert not path.exists()


def test_cleanup_retries_deleted_marker_after_database_failure(app, monkeypatch):
    now = datetime.now(UTC)
    path = _add_expired_manifest(app, "marker-retry-job", now)
    real_commit = db.session.commit
    calls = 0

    def fail_marker_commit():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("database unavailable")
        return real_commit()

    monkeypatch.setattr(db.session, "commit", fail_marker_commit)
    with app.app_context():
        assert cleanup_expired_results(now) == 1
        assert not path.exists()
        artifact = db.session.scalar(
            db.select(AnalysisArtifact).where(
                AnalysisArtifact.job_id == "marker-retry-job"
            )
        )
        assert artifact.deleted_at is None

    monkeypatch.setattr(db.session, "commit", real_commit)
    with app.app_context():
        assert cleanup_expired_results(now) == 0
        assert db.session.scalar(
            db.select(AnalysisArtifact).where(
                AnalysisArtifact.job_id == "marker-retry-job"
            )
        ).deleted_at is not None


def test_celery_reliability_and_beat_configuration(app):
    celery_config = app.config["CELERY"]
    assert celery_config["task_acks_late"] is True
    assert celery_config["task_reject_on_worker_lost"] is True
    assert celery_config["worker_prefetch_multiplier"] == 1
    assert celery_config["task_soft_time_limit"] < celery_config["task_time_limit"]
    assert celery_config["worker_max_tasks_per_child"] > 0
    assert celery_config["broker_transport_options"]["visibility_timeout"] > (
        celery_config["task_time_limit"]
    )
    schedule = celery_config["beat_schedule"]
    assert schedule["reconcile-pending-risk-dispatches"]["task"] == (
        "app.tasks.maintenance.reconcile_pending_dispatches"
    )
    assert schedule["cleanup-expired-risk-results"]["task"] == (
        "app.tasks.maintenance.cleanup_expired_results"
    )


def test_beat_reconciliation_dispatches_pending_job(app, monkeypatch):
    with app.app_context():
        db.session.add(
            AnalysisJob(
                id="beat-pending-job",
                owner_id=1,
                idempotency_key="beat-key",
                status="QUEUED",
                stage="QUEUED",
                progress=0,
                request_payload=_payload(),
                geometry=_payload()["geometry"],
            )
        )
        db.session.commit()
        sent = []
        monkeypatch.setattr(
            "app.services.job_maintenance.celery.send_task",
            lambda *args, **kwargs: sent.append(kwargs["task_id"]),
        )

        result = reconcile_pending_dispatches.run()

        assert result == {"dispatched": 1, "pending": 1}
        assert sent == ["beat-pending-job"]
        assert db.session.get(AnalysisJob, "beat-pending-job").dispatch_status == (
            "DISPATCHED"
        )
