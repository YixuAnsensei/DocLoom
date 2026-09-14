"""review 预览：把所有章节的提示词、参考资料、token 预算写成 markdown 预览文件，
形成"编辑 prompts.json → 预览 → 再编辑"的循环，不用发请求就能核对每章输入。
"""

from .config import TaskPaths, load_prompts, load_settings, load_task_state
from .pipeline import state_chain_refs
from .refs import (estimate_image_tokens, load_ref_content, resolve_ref_path,
                   split_refs)
from .tokens import TokenCounter
from .utils import atomic_write_text


def generate_review(paths: TaskPaths, log=print) -> str:
    """生成 review 预览，写入 output/review_preview.md 并返回内容。"""
    settings = load_settings(paths)
    prompts = load_prompts(paths)
    state = load_task_state(paths, len(prompts))
    counter = TokenCounter(settings)

    context_window = settings.get("context_window_tokens", 56000)
    max_input = int(context_window * settings.get("max_input_ratio", 0.75))

    lines = [
        f"# Review 预览 — {settings['project_name']}",
        "",
        f"- 任务: `{paths.name}`",
        f"- 模型: `{settings['model']}`  |  API: `{settings['api_url']}`",
        f"- 上下文窗口: {context_window} tokens（输入上限 {max_input}）",
        f"- 视觉模型: {'开启' if settings.get('vision_model') else '关闭'}"
        f"  |  状态链: {'开启' if settings.get('state_chain') else '关闭'}",
        "",
        "## 系统提示词",
        "",
        "```",
        settings["system_prompt"],
        "```",
        "",
    ]

    try:
        for i, p in enumerate(prompts):
            status = state.get(str(i), "pending")
            icon = "✅" if status == "completed" else "⬜"
            lines += [f"## {icon} 第 {i + 1} 章：{p['chapter']}", ""]

            ref_files = list(p.get("ref_files", []))
            chain_files = state_chain_refs(paths, i, settings, log=lambda *_: None)
            text_refs, image_refs = split_refs(paths, ref_files + chain_files)
            ref_content = load_ref_content(
                paths, text_refs, image_refs, settings, log=lambda *_: None)

            prompt_tokens = counter.count(p["prompt"])
            ref_tokens = counter.count(ref_content)
            img_tokens = estimate_image_tokens(len(image_refs), settings)
            sys_tokens = counter.count(settings["system_prompt"])
            total = prompt_tokens + ref_tokens + img_tokens + sys_tokens + 300
            pct = round(total / context_window * 100, 1)
            over = "  ⚠️ 超出输入上限，运行时将触发截断" if total > max_input else ""

            missing = [f for f in ref_files
                       if resolve_ref_path(paths, f) is None]

            lines += [
                f"- 状态: {status}",
                f"- 参考资料: {', '.join(ref_files) if ref_files else '（无）'}"
                + (f"  |  状态链注入: {', '.join(chain_files)}" if chain_files else ""),
            ]
            if missing:
                lines.append(f"- ⚠️ 缺失的参考文件: {', '.join(missing)}")
            if image_refs:
                lines.append(f"- 参考图片: {len(image_refs)} 张")
            hints = p.get("image_hints", [])
            if hints:
                lines.append(f"- 配图建议: {len(hints)} 处（{'; '.join(hints)}）")
            lines += [
                f"- token 预算（{counter.source_label}）: 系统 {sys_tokens} + 提示词 {prompt_tokens}"
                f" + 参考 {ref_tokens} + 图片 {img_tokens} ≈ **{total}** / 窗口 {context_window}"
                f"（{pct}%）{over}",
                "",
                "### 提示词全文",
                "",
                "```",
                p["prompt"],
                "```",
                "",
            ]
    finally:
        counter.close()

    content = "\n".join(lines)
    atomic_write_text(paths.review_path, content)
    log(f"[预览] 已生成 review 预览文件: {paths.review_path}")
    log("用任意 Markdown 阅读器打开核对，修改 config/prompts.json 后重新运行 review 即可刷新。")
    log("确认无误后运行: docloom run")
    return content
