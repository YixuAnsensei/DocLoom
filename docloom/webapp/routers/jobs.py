"""运行与产物层：预处理(parse/抽图/caption)、生成、修改、联网检索、
运行日志、成品输出、参考资料清单、review 预览。"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ...config import load_settings
from ...refs import list_reference_files
from ..deps import Ctx
from ..models import IngestBody, ModifyBody, ResearchBody, RunBody


def build_router(ctx: Ctx) -> APIRouter:
    router = APIRouter()

    @router.post("/api/tasks/{name}/ingest")
    def api_ingest(name: str, body: IngestBody):
        paths = ctx.get_task(name)
        kind = body.kind

        async def do_ingest(log):
            if kind == "parse":
                from ...ingest.parser import convert_all
                paths.processed_dir.mkdir(parents=True, exist_ok=True)
                convert_all(paths.raw_dir, paths.processed_dir, log=log)
            elif kind == "extract-images":
                from ...ingest.images import extract_all
                paths.images_dir.mkdir(parents=True, exist_ok=True)
                extract_all(paths.raw_dir, paths.images_dir, log=log)
            elif kind == "caption":
                from ...captions import generate_captions
                await generate_captions(paths, log=log)
            else:
                log(f"[错误] 未知的 ingest 类型: {kind}")

        if kind not in ("parse", "extract-images", "caption"):
            raise HTTPException(400, "kind 必须是 parse / extract-images / caption")
        if not ctx.runs.start(name, f"ingest:{kind}", do_ingest):
            raise HTTPException(409, "该任务已有后台运行在进行中")
        return {"ok": True}

    @router.post("/api/tasks/{name}/run")
    def api_run(name: str, body: RunBody):
        from ...pipeline import run_scheduler
        paths = ctx.get_task(name)
        started = ctx.runs.start(
            name, "run",
            lambda log: run_scheduler(paths, run_index=body.index, log=log))
        if not started:
            raise HTTPException(409, "该任务已有后台运行在进行中")
        return {"ok": True}

    @router.post("/api/tasks/{name}/modify")
    def api_modify(name: str, body: ModifyBody):
        from ...pipeline import run_modifications
        paths = ctx.get_task(name)
        started = ctx.runs.start(
            name, "modify",
            lambda log: run_modifications(
                paths, [(body.index, body.instruction)], log=log))
        if not started:
            raise HTTPException(409, "该任务已有后台运行在进行中")
        return {"ok": True}

    @router.post("/api/tasks/{name}/research")
    def api_research(name: str, body: ResearchBody):
        from ...research import run_research
        paths = ctx.get_task(name)
        queries = [q.strip() for q in body.queries if q.strip()]
        if not queries and body.chapter_index is None:
            raise HTTPException(400, "请提供检索词，或指定章节编号自动生成检索词")
        started = ctx.runs.start(
            name, "research",
            lambda log: run_research(
                paths, queries=queries or None,
                chapter_index=body.chapter_index,
                name=body.name.strip(), log=log))
        if not started:
            raise HTTPException(409, "该任务已有后台运行在进行中")
        return {"ok": True}

    @router.get("/api/tasks/{name}/log")
    def api_log(name: str):
        return {"running": ctx.runs.is_running(name), "lines": ctx.runs.log_lines(name)}

    @router.get("/api/tasks/{name}/output")
    def api_output(name: str):
        paths = ctx.get_task(name)
        settings = load_settings(paths)
        output_path = paths.output_path(settings)
        text = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        return JSONResponse({"file": str(output_path), "content": text})

    @router.get("/api/tasks/{name}/refs")
    def api_refs(name: str):
        return list_reference_files(ctx.get_task(name))

    @router.get("/api/tasks/{name}/review")
    def api_review(name: str):
        from ...review import generate_review
        content = generate_review(ctx.get_task(name), log=lambda *_: None)
        return JSONResponse({"content": content})

    return router
