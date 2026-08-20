from threading import Lock

import pytest

from app import create_app
from app.config import TestingConfig
from app.extensions import db
from app.models import User


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.counters = {}
        self.lock = Lock()

    def exists(self, key):
        return key in self.values

    def setex(self, key, _ttl, value):
        self.values[key] = value

    def eval(self, _script, _numkeys, key, _window):
        with self.lock:
            self.counters[key] = self.counters.get(key, 0) + 1
            return [self.counters[key], 60]


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
    application.extensions["redis_auth"] = FakeRedis()
    with application.app_context():
        db.create_all()
        user = User(username="test-user")
        user.set_password("test-password")
        db.session.add(user)
        db.session.commit()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    from flask_jwt_extended import create_access_token

    client = app.test_client()
    with app.app_context():
        client.environ_base["HTTP_AUTHORIZATION"] = (
            f"Bearer {create_access_token(identity='1')}"
        )
    return client


@pytest.fixture()
def anonymous_client(app):
    return app.test_client()
