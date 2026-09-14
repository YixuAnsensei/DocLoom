"""路由共享上下文：把原先 create_app 内的闭包（workspace 根、运行管理、
两个校验辅助）收敛成一个对象，传给各 router 使用。"""

from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from ..config import TaskPaths, resolve_task
from .runner import RunManager


@dataclass
class Ctx:
    ws_root: Path
    runs: RunManager

    def get_task(self, name: str) -> TaskPaths:
        try:
            return resolve_task(self.ws_root, name)
        except SystemExit:
            raise HTTPException(404, f"任务不存在: {name}")

    def ensure_idle(self, name: str) -> None:
        """有后台运行时禁止改配置/状态/报告，避免写冲突。"""
        if self.runs.is_running(name):
            raise HTTPException(409, "该任务正有后台运行，请等它结束后再操作")
