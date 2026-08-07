from celery import Celery
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from redis import Redis
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)
migrate = Migrate()
jwt = JWTManager()
cors = CORS()
celery = Celery("esr_platform")


def create_redis_client(url: str) -> Redis:
    return Redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
