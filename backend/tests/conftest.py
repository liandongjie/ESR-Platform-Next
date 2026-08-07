import pytest

from app import create_app


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("ESR_RUNTIME_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("ESR_SOURCE_RASTER_DIR", str(tmp_path / "source"))

    application = create_app("testing")
    application.config.update(TESTING=True)
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()
