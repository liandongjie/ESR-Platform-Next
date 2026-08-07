from app.extensions import celery as celery_app


@celery_app.task(name="app.tasks.health.ping")
def ping() -> dict[str, str]:
    return {"status": "ok"}
