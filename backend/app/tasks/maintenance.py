from app.extensions import celery as celery_app
from app.services.job_maintenance import cleanup_expired_results, dispatch_pending_jobs


@celery_app.task(name="app.tasks.maintenance.reconcile_pending_dispatches")
def reconcile_pending_dispatches() -> dict[str, int]:
    dispatched, total = dispatch_pending_jobs()
    return {"dispatched": dispatched, "pending": total}


@celery_app.task(name="app.tasks.maintenance.cleanup_expired_results")
def cleanup_expired_results_task() -> dict[str, int]:
    return {"expired": cleanup_expired_results()}
