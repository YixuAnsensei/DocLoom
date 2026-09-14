"""任务与配置层：模板列表、任务增查、导出模板、settings/prompts 读写、状态重置。"""

from fastapi import APIRouter, Body, HTTPException

from ...config import (load_prompts, load_settings, load_task_state, list_tasks,
                       save_task_state, templates_root)
from ...utils import save_json
from ..deps import Ctx
from ..models import NewTaskBody, RunBody, SaveTemplateBody


def build_router(ctx: Ctx) -> APIRouter:
    router = APIRouter()

    @router.get("/api/templates")
    def api_templates():
        tpl_root = templates_root()
        out = []
        if tpl_root.exists():
            for d in sorted(tpl_root.iterdir()):
                if d.is_dir():
                    desc_file = d / "description.md"
                    desc = (desc_file.read_text(encoding="utf-8").strip().splitlines()[0]
                            if desc_file.exists() else "")
                    out.append({"name": d.name, "description": desc})
        return out

    @router.get("/api/tasks")
    def api_tasks():
        out = []
        for t in list_tasks(ctx.ws_root):
            settings = load_settings(t)
            prompts = load_prompts(t)
            state = load_task_state(t, len(prompts))
            done = sum(1 for i in range(len(prompts))
                       if state.get(str(i)) == "completed")
            out.append({
                "name": t.name,
                "project_name": settings.get("project_name", ""),
                "chapters": len(prompts),
                "completed": done,
                "running": ctx.runs.is_running(t.name),
            })
        return out

    @router.post("/api/tasks")
    def api_new_task(body: NewTaskBody):
        from ...cli import cmd_new

        class Args:
            pass
        a = Args()
        a.workspace = str(ctx.ws_root.parent)
        a.name = body.name
        a.template = body.template
        try:
            cmd_new(a)
        except SystemExit:
            raise HTTPException(400, "创建失败：任务已存在或模板无效")
        return {"ok": True}

    @router.post("/api/tasks/{name}/save-template")
    def api_save_template(name: str, body: SaveTemplateBody):
        from ...config import export_template
        paths = ctx.get_task(name)
        if not body.name.strip():
            raise HTTPException(400, "请填写模板名")
        try:
            target = export_template(paths, body.name.strip(),
                                     description=body.description, force=body.force)
        except FileExistsError:
            raise HTTPException(409, "同名模板已存在（勾选覆盖后重试）")
        return {"ok": True, "path": str(target)}

    @router.get("/api/tasks/{name}/settings")
    def api_get_settings(name: str):
        return load_settings(ctx.get_task(name))

    @router.put("/api/tasks/{name}/settings")
    def api_put_settings(name: str, body: dict):
        paths = ctx.get_task(name)
        ctx.ensure_idle(name)
        save_json(paths.settings_path, body)
        return {"ok": True}

    @router.get("/api/tasks/{name}/prompts")
    def api_get_prompts(name: str):
        return load_prompts(ctx.get_task(name))

    @router.put("/api/tasks/{name}/prompts")
    def api_put_prompts(name: str, body: list = Body(...)):
        paths = ctx.get_task(name)
        ctx.ensure_idle(name)
        for i, item in enumerate(body):
            if not isinstance(item, dict) or not str(item.get("chapter", "")).strip():
                raise HTTPException(400, f"第 {i + 1} 个章节缺少有效的 chapter 标题")
            if "prompt" not in item:
                raise HTTPException(400, f"第 {i + 1} 个章节缺少 prompt 字段")
        save_json(paths.prompts_path, body)
        return {"ok": True}

    @router.post("/api/tasks/{name}/reset")
    def api_reset(name: str, body: RunBody):
        paths = ctx.get_task(name)
        ctx.ensure_idle(name)
        prompts = load_prompts(paths)
        state = load_task_state(paths, len(prompts))
        if body.index is None:
            state = {str(i): "pending" for i in range(len(prompts))}
        elif 0 <= body.index < len(prompts):
            state[str(body.index)] = "pending"
        else:
            raise HTTPException(400, "章节编号超出范围")
        save_task_state(paths, state)
        return {"ok": True}

    return router
