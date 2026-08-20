from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _load_revision(filename: str):
    path = Path(__file__).parents[1] / "migrations" / "versions" / filename
    spec = spec_from_file_location(filename.removesuffix(".py"), path)
    if spec is None or spec.loader is None:  # pragma: no cover - fixed repository path
        raise RuntimeError(f"Cannot load migration revision: {path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sqlite_migrations_upgrade_downgrade_roundtrip(tmp_path, monkeypatch):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.sqlite3'}")
    revisions = [
        _load_revision("20260820_01_multi_user_jobs.py"),
        _load_revision("20260820_02_job_dispatch_state.py"),
        _load_revision("20260820_03_job_lifecycle.py"),
    ]
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        for revision in revisions:
            monkeypatch.setattr(revision, "op", operations)
            revision.upgrade()

        columns = {column["name"] for column in sa.inspect(connection).get_columns("analysis_jobs")}
        assert {"idempotency_key", "parent_job_id", "expires_at"} <= columns
        revisions[-1].downgrade()
        downgraded = {
            column["name"]
            for column in sa.inspect(connection).get_columns("analysis_jobs")
        }
        assert "idempotency_key" not in downgraded
        revisions[-1].upgrade()
        upgraded = {
            column["name"]
            for column in sa.inspect(connection).get_columns("analysis_jobs")
        }
        assert {"idempotency_key", "parent_job_id", "expires_at"} <= upgraded
