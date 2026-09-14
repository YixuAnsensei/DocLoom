"""通用小工具：原子写入、JSON 读写、思维链剥离。"""

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """先写临时文件再重命名，避免断电/中断导致文件损坏。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
        os.replace(tmp_name, str(path))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_json(path: Path, default):
    """读取 JSON 文件，不存在时用 default 创建。"""
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    save_json(path, default)
    return default


def save_json(path: Path, data) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def strip_think(text: str) -> str:
    """剥离 Qwen 等模型输出中的 <think>...</think> 思维链片段。"""
    return THINK_RE.sub("", text).lstrip()


class LogTee:
    """向终端和任务日志文件同时写入运行信息。"""

    def __init__(self, task_dir: Path, kind: str, output=print):
        self.output = output
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = task_dir / "logs" / f"{kind}_{stamp}.log"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, *parts) -> None:
        line = " ".join(str(part) for part in parts)
        self.output(line)
        with self.path.open("a", encoding="utf-8", newline="") as f:
            f.write(line + "\n")


def recent_log_path(task_dir: Path) -> Path | None:
    """返回任务最近一次运行日志，不存在时返回 None。"""
    log_dir = task_dir / "logs"
    logs = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def make_zip(output: Path, files: dict[str, Path], log=print) -> bool:
    """将一组路径（dict: 档案内文件名 → 真实路径）打包为 .zip。"""
    import zipfile

    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(str(output), "w", zipfile.ZIP_DEFLATED,
                             compresslevel=6) as zf:
            for name, fpath in files.items():
                if fpath.exists():
                    zf.write(str(fpath), arcname=name)
                    log(f"  + {name}")
                else:
                    log(f"  ! 跳过（不存在）: {name}")
        return True
    except Exception as err:
        log(f"[导出错误] {err}")
        return False
