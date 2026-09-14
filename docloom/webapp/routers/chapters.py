"""章节层：章节列表/详情、增删换序、候选稿接受/放弃、章节参考资料设置。"""

from fastapi import APIRouter, Body, HTTPException

from ...config import load_prompts, load_settings, load_task_state
from ...refs import resolve_ref_path
from ...report import parse_report_chapter
from ...utils import save_json
from ..deps import Ctx
from ..models import AddChapterBody, MoveChapterBody


def build_router(ctx: Ctx) -> APIRouter:
    router = APIRouter()

    @router.get("/api/tasks/{name}/chapters")
    def api_chapters(name: str):
        from ...pipeline import list_candidates
        paths = ctx.get_task(name)
        settings = load_settings(paths)
        prompts = load_prompts(paths)
        state = load_task_state(paths, len(prompts))
        candidates = {c["index"] for c in list_candidates(paths)}
        output_path = paths.output_path(settings)
        all_names = [p["chapter"] for p in prompts]
        out = []
        for i, p in enumerate(prompts):
            content = parse_report_chapter(output_path, p["chapter"], all_names)
            out.append({
                "index": i,
                "chapter": p["chapter"],
                "status": state.get(str(i), "pending"),
                "has_content": content is not None,
                "has_candidate": i in candidates,
                "ref_files": p.get("ref_files", []),
                "image_hints": p.get("image_hints", []),
            })
        return out

    @router.get("/api/tasks/{name}/chapters/{index}")
    def api_chapter_detail(name: str, index: int):
        from ...pipeline import candidate_paths
        paths = ctx.get_task(name)
        settings = load_settings(paths)
        prompts = load_prompts(paths)
        if index < 0 or index >= len(prompts):
            raise HTTPException(404, "章节不存在")
        all_names = [p["chapter"] for p in prompts]
        content = parse_report_chapter(
            paths.output_path(settings), prompts[index]["chapter"], all_names)
        md_path, _ = candidate_paths(paths, index)
        candidate = md_path.read_text(encoding="utf-8") if md_path.exists() else None
        return {
            "index": index,
            "prompt_def": prompts[index],
            "content": content,
            "candidate": candidate,
        }

    @router.post("/api/tasks/{name}/chapters")
    def api_add_chapter(name: str, body: AddChapterBody):
        from ...pipeline import add_chapter
        paths = ctx.get_task(name)
        ctx.ensure_idle(name)
        if not body.chapter.strip():
            raise HTTPException(400, "章节标题不能为空")
        idx = add_chapter(paths, body.chapter.strip(), body.prompt,
                          log=lambda *_: None)
        return {"ok": True, "index": idx}

    @router.delete("/api/tasks/{name}/chapters/{index}")
    def api_delete_chapter(name: str, index: int):
        from ...pipeline import delete_chapter
        paths = ctx.get_task(name)
        ctx.ensure_idle(name)
        if not delete_chapter(paths, index, log=lambda *_: None):
            raise HTTPException(400, "章节编号超出范围")
        return {"ok": True}

    @router.post("/api/tasks/{name}/chapters/{index}/move")
    def api_move_chapter(name: str, index: int, body: MoveChapterBody):
        from ...pipeline import move_chapter
        paths = ctx.get_task(name)
        ctx.ensure_idle(name)
        if not move_chapter(paths, index, body.delta, log=lambda *_: None):
            raise HTTPException(400, "移动越界或章节编号无效")
        return {"ok": True}

    @router.post("/api/tasks/{name}/chapters/{index}/accept")
    def api_accept(name: str, index: int):
        from ...pipeline import accept_candidate
        ctx.ensure_idle(name)
        lines = []
        ok = accept_candidate(ctx.get_task(name), index, log=lambda *p: lines.append(" ".join(map(str, p))))
        return {"ok": ok, "log": lines}

    @router.post("/api/tasks/{name}/chapters/{index}/reject")
    def api_reject(name: str, index: int):
        from ...pipeline import reject_candidate
        ctx.ensure_idle(name)
        lines = []
        ok = reject_candidate(ctx.get_task(name), index, log=lambda *p: lines.append(" ".join(map(str, p))))
        return {"ok": ok, "log": lines}

    @router.put("/api/tasks/{name}/chapters/{index}/refs")
    def api_put_chapter_refs(name: str, index: int, body: list = Body(...)):
        """直接设置第 index 章的 ref_files（覆盖现有）。"""
        paths = ctx.get_task(name)
        ctx.ensure_idle(name)
        prompts = load_prompts(paths)
        if index < 0 or index >= len(prompts):
            raise HTTPException(404, "章节不存在")
        for item in body:
            if not isinstance(item, str) or not item.strip() or resolve_ref_path(paths, item) is None:
                raise HTTPException(400, f"无效或不存在的参考资料: {item}")
        prompts[index]["ref_files"] = [item.strip() for item in body]
        save_json(paths.prompts_path, prompts)
        return {"ok": True}

    return router
