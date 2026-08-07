from __future__ import annotations

from celery import Task

from app.extensions import celery as celery_app
from app.factory import create_app

flask_app = create_app()
celery_app.config_from_object(flask_app.config["CELERY"])
celery_app.set_default()
celery_app.autodiscover_tasks(["app.tasks"])


class FlaskTask(Task):
    abstract = True

    def __call__(self, *args, **kwargs):
        with flask_app.app_context():
            return self.run(*args, **kwargs)


celery_app.Task = FlaskTask

__all__ = ["celery_app"]
