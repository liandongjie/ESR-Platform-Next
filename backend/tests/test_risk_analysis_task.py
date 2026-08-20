from app.extensions import db
from app.models import AnalysisJob
from app.repositories.risk_analysis_job_store import RiskAnalysisJobStore
from app.tasks.risk_analysis import _persist_failure_safely, run_risk_analysis


def test_risk_analysis_task_has_stable_celery_name():
    assert run_risk_analysis.name == "app.tasks.risk_analysis.run"


def test_worker_failure_state_does_not_depend_on_manifest(app, monkeypatch):
    payload = {
        "geometry": {"type": "Point", "coordinates": [118.9, 32.1]},
        "weights": [{"code": "PM25", "weight_percent": 100}],
    }
    with app.app_context():
        db.session.add(
            AnalysisJob(
                id="failed-job",
                owner_id=1,
                idempotency_key="failed-key",
                status="RUNNING",
                stage="ANALYZING",
                progress=50,
                request_payload=payload,
                geometry=payload["geometry"],
            )
        )
        db.session.commit()
        monkeypatch.setattr(
            "app.tasks.risk_analysis.write_failure_manifest",
            lambda **kwargs: (_ for _ in ()).throw(OSError("disk unavailable")),
        )

        _persist_failure_safely(
            task_id="failed-job",
            runtime_dir=app.config["RUNTIME_DATA_DIR"],
            error_code="ANALYSIS_ERROR",
            message="analysis failed",
        )

        job = db.session.get(AnalysisJob, "failed-job")
        assert job.status == "FAILED"
        assert job.stage == "FAILED"
        assert job.error_code == "ANALYSIS_ERROR"
        assert job.error_message == "analysis failed"


def test_late_worker_failure_does_not_overwrite_success_manifest(app):
    payload = {
        "geometry": {"type": "Point", "coordinates": [118.9, 32.1]},
        "weights": [{"code": "PM25", "weight_percent": 100}],
    }
    success = {"task_id": "successful-job", "status": "SUCCEEDED"}
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    store.write_json(
        task_id="successful-job", filename="result.json", payload=success
    )
    with app.app_context():
        db.session.add(
            AnalysisJob(
                id="successful-job",
                owner_id=1,
                idempotency_key="successful-key",
                status="SUCCEEDED",
                stage="COMPLETED",
                progress=100,
                request_payload=payload,
                geometry=payload["geometry"],
            )
        )
        db.session.commit()

        _persist_failure_safely(
            task_id="successful-job",
            runtime_dir=app.config["RUNTIME_DATA_DIR"],
            error_code="LATE_FAILURE",
            message="late delivery failed",
        )

        assert db.session.get(AnalysisJob, "successful-job").status == "SUCCEEDED"
        assert store.read_result("successful-job") == success


def test_transient_io_failure_retries_only_twice(app, monkeypatch):
    payload = {
        "geometry": {"type": "Point", "coordinates": [118.9, 32.1]},
        "weights": [{"code": "PM25", "weight_percent": 100}],
    }
    calls = 0

    def fail_transiently(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise OSError("temporary storage failure")

    monkeypatch.setattr(
        "app.tasks.risk_analysis.RiskAnalysisJobService.execute",
        fail_transiently,
    )
    monkeypatch.setattr(run_risk_analysis.app.conf, "task_eager_propagates", False)
    with app.app_context():
        db.session.add(
            AnalysisJob(
                id="retry-job",
                owner_id=1,
                idempotency_key="retry-job-key",
                status="QUEUED",
                stage="QUEUED",
                progress=0,
                request_payload=payload,
                geometry=payload["geometry"],
            )
        )
        db.session.commit()

        result = run_risk_analysis.apply(
            args=[payload], task_id="retry-job", throw=False
        )

        assert result.failed()
        assert calls == 3
        job = db.session.get(AnalysisJob, "retry-job")
        assert job.status == "FAILED"
        assert job.error_code == "TRANSIENT_IO_ERROR"


def test_deterministic_validation_failure_is_not_retried(app):
    payload = {
        "geometry": {"type": "Point", "coordinates": [118.9, 32.1]},
        "weights": [],
    }
    with app.app_context():
        db.session.add(
            AnalysisJob(
                id="invalid-job",
                owner_id=1,
                idempotency_key="invalid-job-key",
                status="QUEUED",
                stage="QUEUED",
                progress=0,
                request_payload=payload,
                geometry=payload["geometry"],
            )
        )
        db.session.commit()

        result = run_risk_analysis.apply(
            args=[payload], task_id="invalid-job", throw=False
        )

        assert result.failed()
        job = db.session.get(AnalysisJob, "invalid-job")
        assert job.status == "FAILED"
        assert job.error_code == "INVALID_REQUEST"


def test_worker_reclaims_only_broker_marked_redelivery(app, monkeypatch):
    payload = {
        "geometry": {"type": "Point", "coordinates": [118.9, 32.1]},
        "weights": [{"code": "PM25", "weight_percent": 100}],
    }
    calls = []
    monkeypatch.setattr(
        "app.tasks.risk_analysis.RiskAnalysisJobService.execute",
        lambda *args, **kwargs: calls.append(kwargs["task_id"])
        or {"artifacts": {}},
    )
    with app.app_context():
        for task_id in ("ordinary-duplicate", "broker-redelivery"):
            db.session.add(
                AnalysisJob(
                    id=task_id,
                    owner_id=1,
                    idempotency_key=f"{task_id}-key",
                    status="RUNNING",
                    stage="ANALYZING",
                    progress=35,
                    request_payload=payload,
                    geometry=payload["geometry"],
                )
            )
        db.session.commit()

        run_risk_analysis.push_request(
            id="ordinary-duplicate", delivery_info={}
        )
        try:
            ordinary = run_risk_analysis.run(payload)
        finally:
            run_risk_analysis.pop_request()
        run_risk_analysis.push_request(
            id="broker-redelivery", delivery_info={"redelivered": True}
        )
        try:
            redelivered = run_risk_analysis.run(payload)
        finally:
            run_risk_analysis.pop_request()

        assert ordinary["status"] == "IGNORED"
        assert redelivered["artifacts"] == {}
        assert calls == ["broker-redelivery"]
        assert db.session.get(AnalysisJob, "ordinary-duplicate").status == "RUNNING"
        assert db.session.get(AnalysisJob, "broker-redelivery").status == "SUCCEEDED"
