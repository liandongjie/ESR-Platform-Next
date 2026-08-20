import os

import click
from flask import Flask

from app.extensions import db
from app.models import User
from app.services.job_maintenance import dispatch_pending_jobs


def register_cli(app: Flask) -> None:
    @app.cli.command("create-demo-user")
    @click.option("--username", default="demo", show_default=True)
    def create_demo_user(username: str) -> None:
        """Create or update the demo user from ESR_DEMO_USER_PASSWORD."""

        password = os.getenv("ESR_DEMO_USER_PASSWORD")
        if not password or len(password) < 8:
            raise click.ClickException("ESR_DEMO_USER_PASSWORD must contain at least 8 characters")

        user = db.session.scalar(db.select(User).where(User.username == username))
        if user is None:
            user = User(username=username)
            db.session.add(user)
        user.set_password(password)
        user.is_active = True
        db.session.commit()
        click.echo(f"Demo user ready: {username}")

    @app.cli.command("reconcile-risk-dispatches")
    @click.option("--limit", type=click.IntRange(1, 1000), default=100, show_default=True)
    def reconcile_risk_dispatches(limit: int) -> None:
        """Re-send queued jobs left pending between database commit and dispatch."""

        dispatched, total = dispatch_pending_jobs(limit)
        click.echo(f"Reconciled {dispatched}/{total} pending dispatches")
        if dispatched != total:
            raise click.ClickException(f"{total - dispatched} dispatches remain pending")
