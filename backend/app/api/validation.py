from __future__ import annotations

from pydantic import ValidationError


def validation_details(error: ValidationError) -> list[dict[str, str]]:
    """把 Pydantic 错误压缩为稳定、可 JSON 化的 API 字段。"""

    details: list[dict[str, str]] = []
    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item.get("loc", ()))
        details.append(
            {
                "field": location,
                "message": str(item.get("msg", "Invalid value")),
                "type": str(item.get("type", "validation_error")),
            }
        )
    return details
