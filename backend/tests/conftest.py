import pytest

from app import create_app
from app.config import TestingConfig


@pytest.fixture()
def app(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    source_dir = tmp_path / "source"

    # 配置类在模块导入时已经读取环境变量；fixture 阶段再 setenv 无法改变这些类属性。
    # 因此测试直接覆盖 TestingConfig，确保 create_app 建目录前就使用 pytest 的临时路径。
    monkeypatch.setattr(TestingConfig, "RUNTIME_DATA_DIR", runtime_dir)
    monkeypatch.setattr(TestingConfig, "SOURCE_RASTER_DIR", source_dir)

    application = create_app("testing")
    application.config.update(TESTING=True)
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()
