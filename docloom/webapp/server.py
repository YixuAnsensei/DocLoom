"""DocLoom Web UI 后端。

设计：每个任务同一时间只允许一个后台运行；运行日志进内存环形缓冲，
前端轮询 /api/tasks/<t>/log 获取进度。所有引擎调用都走 pipeline 模块，
与 CLI 共享同一套逻辑。

路由按领域拆到 webapp/routers/ 下：
  tasks    —— 任务与配置（模板/任务/settings/prompts/reset）
  chapters —— 章节结构与候选稿（增删换序/accept/reject/refs）
  jobs     —— 运行与产物（生成/修改/检索/预处理/日志/输出/review）
共享上下文（workspace 根 + 后台运行管理）见 webapp/deps.py。
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from .deps import Ctx
from .routers import chapters, jobs, tasks
from .runner import RunManager

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(ws_root: Path) -> FastAPI:
    app = FastAPI(title="DocLoom", docs_url=None, redoc_url=None)
    ctx = Ctx(ws_root=ws_root, runs=RunManager())

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.include_router(tasks.build_router(ctx))
    app.include_router(chapters.build_router(ctx))
    app.include_router(jobs.build_router(ctx))
    return app
