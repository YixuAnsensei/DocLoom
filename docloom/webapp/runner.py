"""后台运行管理：每个任务同一时间只允许一个后台运行，日志进内存环形缓冲。"""

import asyncio
import threading
from collections import deque


class RunManager:
    """管理各任务的后台运行与日志缓冲。"""

    def __init__(self):
        self._runs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _entry(self, task: str) -> dict:
        with self._lock:
            return self._runs.setdefault(
                task, {"running": False, "log": deque(maxlen=2000), "kind": ""})

    def is_running(self, task: str) -> bool:
        return self._entry(task)["running"]

    def log_lines(self, task: str) -> list[str]:
        return list(self._entry(task)["log"])

    def start(self, task: str, kind: str, coro_factory) -> bool:
        """启动后台线程执行协程；已有运行时返回 False。"""
        entry = self._entry(task)
        with self._lock:
            if entry["running"]:
                return False
            entry["running"] = True
            entry["kind"] = kind
            entry["log"].clear()

        def log(*parts):
            entry["log"].append(" ".join(str(p) for p in parts))

        def worker():
            try:
                asyncio.run(coro_factory(log))
            except Exception as e:  # 后台线程兜底，异常写入日志而不是丢失
                log(f"[异常] {type(e).__name__}: {e}")
            finally:
                entry["running"] = False
                log("[后台任务结束]")

        threading.Thread(target=worker, daemon=True).start()
        return True
