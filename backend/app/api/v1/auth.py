from __future__ import annotations

from datetime import UTC, datetime

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
    set_refresh_cookies,
    unset_jwt_cookies,
)
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.api.validation import validation_details
from app.extensions import db
from app.models import User
from app.schemas.auth import CredentialsInput

auth_bp = Blueprint("auth", __name__)


def _user_payload(user: User) -> dict[str, object]:
    return {"id": user.id, "username": user.username}


def _credentials():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, (jsonify({"code": "INVALID_JSON", "message": "请求体必须是 JSON object"}), 400)
    try:
        return CredentialsInput.model_validate(payload), None
    except ValidationError as exc:
        return None, (
            jsonify(
                {
                    "code": "INVALID_REQUEST",
                    "message": "用户名或密码格式不正确",
                    "details": validation_details(exc),
                }
            ),
            422,
        )


def _authenticated_response(user: User):
    response = jsonify(
        {
            "access_token": create_access_token(identity=str(user.id)),
            "user": _user_payload(user),
        }
    )
    set_refresh_cookies(response, create_refresh_token(identity=str(user.id)))
    response.headers["Cache-Control"] = "no-store"
    return response


@auth_bp.post("/register")
def register():
    if not current_app.config["REGISTRATION_ENABLED"]:
        return jsonify({"code": "REGISTRATION_DISABLED", "message": "当前环境未开放注册"}), 403

    credentials, error = _credentials()
    if error is not None:
        return error
    if db.session.scalar(db.select(User).where(User.username == credentials.username)):
        return jsonify({"code": "USERNAME_TAKEN", "message": "用户名已存在"}), 409

    user = User(username=credentials.username)
    user.set_password(credentials.password)
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"code": "USERNAME_TAKEN", "message": "用户名已存在"}), 409
    return _authenticated_response(user), 201


@auth_bp.post("/login")
def login():
    credentials, error = _credentials()
    if error is not None:
        return error
    user = db.session.scalar(db.select(User).where(User.username == credentials.username))
    if user is None or not user.is_active or not user.check_password(credentials.password):
        return jsonify({"code": "INVALID_CREDENTIALS", "message": "用户名或密码错误"}), 401
    return _authenticated_response(user)


@auth_bp.post("/refresh")
@jwt_required(refresh=True, locations=["cookies"])
def refresh():
    user = db.session.get(User, int(get_jwt_identity()))
    if user is None or not user.is_active:
        return jsonify({"code": "USER_UNAVAILABLE", "message": "用户不存在或已停用"}), 401
    response = jsonify(
        {"access_token": create_access_token(identity=str(user.id)), "user": _user_payload(user)}
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@auth_bp.post("/logout")
@jwt_required(refresh=True, locations=["cookies"])
def logout():
    token = get_jwt()
    ttl_seconds = max(1, int(token["exp"] - datetime.now(UTC).timestamp()))
    current_app.extensions["redis_auth"].setex(
        f"jwt:revoked:{token['jti']}", ttl_seconds, "1"
    )
    response = jsonify({"message": "已退出登录"})
    unset_jwt_cookies(response)
    response.headers["Cache-Control"] = "no-store"
    return response


@auth_bp.get("/me")
@jwt_required()
def me():
    user = db.session.get(User, int(get_jwt_identity()))
    if user is None or not user.is_active:
        return jsonify({"code": "USER_UNAVAILABLE", "message": "用户不存在或已停用"}), 401
    response = jsonify({"user": _user_payload(user)})
    response.headers["Cache-Control"] = "no-store"
    return response
