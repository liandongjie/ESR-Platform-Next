from app.extensions import db
from app.models import AnalysisArtifact, AnalysisJob
from app.repositories.analysis_jobs import (
    claim_job,
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
    release_job_for_retry,
)
from app.services.job_maintenance import dispatch_pending_jobs


def test_worker_state_and_artifact_metadata_are_persisted(app, tmp_path):
    payload = {
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
    runtime_dir = tmp_path / "runtime"
    artifact_path = runtime_dir / "risk-analysis" / "job-1" / "result.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("{}", encoding="utf-8")

    with app.app_context():
        db.session.add(
            AnalysisJob(
                id="job-1",
                owner_id=1,
                idempotency_key="job-1-key",
                status="QUEUED",
                stage="QUEUED",
                progress=0,
                request_payload=payload,
                geometry=payload["geometry"],
            )
        )
        db.session.commit()

        assert claim_job("job-1") is True
        mark_job_running("job-1", "ANALYZING", 35)
        job = db.session.get(AnalysisJob, "job-1")
        assert (job.status, job.stage, job.progress) == ("RUNNING", "ANALYZING", 35)
        assert job.started_at is not None

        mark_job_succeeded(
            "job-1",
            {"artifacts": {"manifest": "risk-analysis/job-1/result.json"}},
            runtime_dir,
            24,
        )
        db.session.refresh(job)
        artifact = db.session.scalar(
            db.select(AnalysisArtifact).where(AnalysisArtifact.job_id == "job-1")
        )
        assert (job.status, job.progress) == ("SUCCEEDED", 100)
        assert artifact.relative_path == "risk-analysis/job-1/result.json"
        assert artifact.size_bytes == 2
        assert artifact.expires_at == job.expires_at


def test_reconcile_pending_dispatch_uses_stable_task_identity(app, monkeypatch):
    payload = {
        "geometry": {"type": "Point", "coordinates": [118.9, 32.1]},
        "weights": [{"code": "PM25", "weight_percent": 100}],
    }
    with app.app_context():
        db.session.add(
            AnalysisJob(
                id="pending-job",
                owner_id=1,
                idempotency_key="pending-key",
                status="QUEUED",
                stage="QUEUED",
                progress=0,
                request_payload=payload,
                geometry=payload["geometry"],
            )
        )
        db.session.commit()

    dispatched = []
    monkeypatch.setattr(
        "app.services.job_maintenance.celery.send_task",
        lambda name, **kwargs: dispatched.append((name, kwargs)),
    )

    result = app.test_cli_runner().invoke(args=["reconcile-risk-dispatches"])

    assert result.exit_code == 0
    assert dispatched == [
        (
            "app.tasks.risk_analysis.run",
            {"kwargs": {"payload": payload}, "task_id": "pending-job"},
        )
    ]
    with app.app_context():
        job = db.session.get(AnalysisJob, "pending-job")
        assert job.dispatch_status == "DISPATCHED"
        assert job.dispatched_at is not None


def test_duplicate_delivery_cannot_regress_terminal_or_duplicate_artifact(
    app, tmp_path
):
    payload = {
        "geometry": {"type": "Point", "coordinates": [118.9, 32.1]},
        "weights": [{"code": "PM25", "weight_percent": 100}],
    }
    relative_path = "risk-analysis/terminal-job/result.json"
    artifact_path = tmp_path / relative_path
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("{}", encoding="utf-8")
    with app.app_context():
        db.session.add(
            AnalysisJob(
                id="terminal-job",
                owner_id=1,
                idempotency_key="terminal-key",
                status="QUEUED",
                stage="QUEUED",
                progress=0,
                request_payload=payload,
                geometry=payload["geometry"],
            )
        )
        db.session.commit()

        assert claim_job("terminal-job") is True
        started_at = db.session.get(AnalysisJob, "terminal-job").started_at
        assert claim_job("terminal-job") is False
        assert claim_job("terminal-job", allow_running_reclaim=True) is True
        assert db.session.get(AnalysisJob, "terminal-job").started_at == started_at
        assert mark_job_succeeded(
            "terminal-job",
            {"artifacts": {"manifest": relative_path}},
            tmp_path,
            24,
        ) is True
        assert claim_job("terminal-job", allow_running_reclaim=True) is False
        assert mark_job_failed("terminal-job", "LATE_FAILURE", "late") is False
        assert mark_job_succeeded(
            "terminal-job",
            {"artifacts": {"manifest": relative_path}},
            tmp_path,
            24,
        ) is False
        job = db.session.get(AnalysisJob, "terminal-job")
        artifacts = db.session.scalars(
            db.select(AnalysisArtifact).where(
                AnalysisArtifact.job_id == "terminal-job"
            )
        ).all()
        assert job.status == "SUCCEEDED"
        assert len(artifacts) == 1


def test_success_records_preview_artifact_metadata(app, tmp_path):
    payload = {
        "geometry": {"type": "Point", "coordinates": [118.9, 32.1]},
        "weights": [{"code": "PM25", "weight_percent": 100}],
    }
    artifact_paths = {
        "manifest": "risk-analysis/preview-job/result.json",
        "raster": "risk-analysis/preview-job/risk.tif",
        "preview": "risk-analysis/preview-job/preview.png",
    }
    for relative_path in artifact_paths.values():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative_path.encode())

    with app.app_context():
        db.session.add(
            AnalysisJob(
                id="preview-job",
                owner_id=1,
                idempotency_key="preview-key",
                status="RUNNING",
                stage="PERSISTING",
                progress=85,
                request_payload=payload,
                geometry=payload["geometry"],
            )
        )
        db.session.commit()

        assert mark_job_succeeded(
            "preview-job", {"artifacts": artifact_paths}, tmp_path, 24
        )
        artifacts = db.session.scalars(
            db.select(AnalysisArtifact)
            .where(AnalysisArtifact.job_id == "preview-job")
            .order_by(AnalysisArtifact.kind)
        ).all()

        assert [artifact.kind for artifact in artifacts] == [
            "manifest",
            "preview",
            "raster",
        ]
        assert all(artifact.size_bytes > 0 for artifact in artifacts)
        assert all(artifact.expires_at is not None for artifact in artifacts)


def test_retry_publish_failure_remains_reconcilable(app):
    payload = {
        "geometry": {"type": "Point", "coordinates": [118.9, 32.1]},
        "weights": [{"code": "PM25", "weight_percent": 100}],
    }
    sent = []
    with app.app_context():
        db.session.add(
            AnalysisJob(
                id="retry-publish-job",
                owner_id=1,
                idempotency_key="retry-publish-key",
                status="RUNNING",
                stage="ANALYZING",
                progress=35,
                dispatch_status="DISPATCHED",
                request_payload=payload,
                geometry=payload["geometry"],
            )
        )
        db.session.commit()

        assert release_job_for_retry("retry-publish-job") is True
        job = db.session.get(AnalysisJob, "retry-publish-job")
        assert (job.status, job.dispatch_status, job.dispatched_at) == (
            "QUEUED",
            "PENDING",
            None,
        )
        assert dispatch_pending_jobs(
            send_task=lambda *args, **kwargs: sent.append(kwargs["task_id"])
        ) == (1, 1)
        assert sent == ["retry-publish-job"]
        assert db.session.get(AnalysisJob, "retry-publish-job").dispatch_status == (
            "DISPATCHED"
        )
