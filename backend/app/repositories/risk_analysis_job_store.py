from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ARTIFACT_ROOT_NAME = "risk-analysis"


class RiskAnalysisJobStore:
    """统一管理风险分析任务的文件目录和 JSON 元数据。

    API 与 Celery Worker 都需要访问同一份任务目录。把路径校验、原子写入和
    JSON 读取集中在这里，可以避免两端各写一套规则后产生目录不一致或路径穿越漏洞。
    """

    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = Path(runtime_dir).expanduser().resolve()
        self.root_dir = self.runtime_dir / _ARTIFACT_ROOT_NAME

    def task_directory(self, task_id: str, *, create: bool = False) -> Path:
        """返回任务目录；task_id 只允许安全文件名字符。"""

        if task_id in {".", ".."} or not _TASK_ID_PATTERN.fullmatch(task_id):
            raise ValueError("task_id 必须以字母或数字开头，且只能包含安全路径字符")

        task_dir = self.root_dir / task_id
        if create:
            task_dir.mkdir(parents=True, exist_ok=True)
        return task_dir

    def relative_path(self, path: Path) -> str:
        """对外只暴露相对 runtime 根目录的 artifact key，不泄露容器绝对路径。"""

        return path.resolve().relative_to(self.runtime_dir).as_posix()

    def write_json(
        self,
        *,
        task_id: str,
        filename: str,
        payload: dict[str, Any],
    ) -> Path:
        """使用临时文件 + replace 原子发布 JSON，避免读取到半写入文件。"""

        if Path(filename).name != filename:
            raise ValueError("filename 必须是单个安全文件名")

        task_dir = self.task_directory(task_id, create=True)
        path = task_dir / filename
        temporary = task_dir / f".{filename}.tmp"
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(path)
        return path

    def read_json(self, *, task_id: str, filename: str) -> dict[str, Any] | None:
        """读取任务 JSON；文件尚未产生时返回 None。"""

        if Path(filename).name != filename:
            raise ValueError("filename 必须是单个安全文件名")

        path = self.task_directory(task_id) / filename
        if not path.is_file():
            return None

        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"任务元数据不是 JSON object: {path}")
        return payload

    def record_submission(
        self,
        *,
        task_id: str,
        request_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """在投递 Celery 前记录任务，使 PENDING 与“不存在的 task_id”可以区分。"""

        payload: dict[str, Any] = {
            "task_id": task_id,
            "status": "QUEUED",
            "submitted_at": datetime.now(UTC).isoformat(),
            "request": request_payload,
        }
        self.write_json(task_id=task_id, filename="submission.json", payload=payload)
        return payload

    def read_submission(self, task_id: str) -> dict[str, Any] | None:
        return self.read_json(task_id=task_id, filename="submission.json")

    def read_result(self, task_id: str) -> dict[str, Any] | None:
        return self.read_json(task_id=task_id, filename="result.json")

    def list_task_ids(self) -> list[str]:
        """列出已有持久化元数据的任务 ID，忽略临时目录和无关文件。"""

        if not self.root_dir.is_dir():
            return []

        task_ids: list[str] = []
        for candidate in self.root_dir.iterdir():
            if not candidate.is_dir():
                continue

            task_id = candidate.name
            if task_id in {".", ".."} or not _TASK_ID_PATTERN.fullmatch(task_id):
                continue

            # 只暴露真正有提交记录或最终结果的目录，避免把 Worker 临时目录误当成历史任务。
            if (candidate / "submission.json").is_file() or (candidate / "result.json").is_file():
                task_ids.append(task_id)
        return task_ids

    def task_exists(self, task_id: str) -> bool:
        """只把有提交记录或最终结果的目录视为已知任务。"""

        try:
            task_dir = self.task_directory(task_id)
        except ValueError:
            return False
        return (task_dir / "submission.json").is_file() or (task_dir / "result.json").is_file()
