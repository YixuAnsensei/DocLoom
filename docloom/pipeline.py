"""核心调度：章节生成、修改（候选稿流程）、批量运行、断点续传。"""

import difflib
import json
from datetime import datetime
from pathlib import Path

import httpx

from .config import (TaskPaths, load_prompts, load_settings, load_task_state,
                     save_task_state)
from .llm import build_generation_request, call_llm
from .report import (append_chapter_to_report, parse_report_chapter,
                     replace_chapter_in_report)
from .tokens import TokenCounter
from .utils import atomic_write_text, load_json, save_json


def state_chain_refs(paths: TaskPaths, index: int, settings: dict, log=print) -> list[str]:
    """State Chain：返回应注入的前序章节缓存文件名列表。"""
    if not settings.get("state_chain", False):
        return []
    limit = settings.get("state_chain_limit", 1)
    added = []
    for prev_idx in range(index - 1, -1, -1):
        if len(added) >= limit:
            break
        prev_file = f"generated_chapter_{prev_idx + 1}.txt"
        if (paths.processed_dir / prev_file).exists():
            added.append(prev_file)
    if added:
        log(f"  [上下文历史] 自动引入前序章节作为参考资料: {', '.join(added)}")
    return added


def save_chapter_history(paths: TaskPaths, index: int, content: str, log=print) -> None:
    """保存章节纯文本副本，供 State Chain 使用。"""
    history_file = paths.processed_dir / f"generated_chapter_{index + 1}.txt"
    try:
        atomic_write_text(history_file, content)
        log(f"  [上下文历史] 已保存该章纯文本副本至: {history_file.name}")
    except OSError as e:
        log(f"  [警告] 无法保存该章上下文历史文件: {e}")


def print_image_hints(prompt_def: dict, log=print) -> None:
    hints = prompt_def.get("image_hints", [])
    if not hints:
        return
    log(f"\n  {'─' * 50}")
    log("  [配图/视频建议] 请在最终报告中补充以下素材：")
    for i, hint in enumerate(hints, 1):
        log(f"    {i}. {hint}")
    log(f"  {'─' * 50}")


def _print_usage(stats: dict, log=print) -> None:
    extra = ""
    if stats.get("image_count"):
        extra = f" + {stats['image_count']} 张图片 (~{stats['image_tokens']} tokens)"
    log(f"  [用量] 输入 ~{stats['total_input']} tokens / 窗口 {stats['context_window']} "
        f"({stats['usage_pct']}%) [{stats['token_source']}]"
        + (" [已截断参考资料]" if stats["truncated"] else "") + extra)
    if stats["usage_pct"] > 90:
        log("  [警告] 输入占比高于 90%，生成输出空间可能不足！建议调大 context_window_tokens。")


async def process_single_chapter(
    client: httpx.AsyncClient,
    index: int,
    prompt_def: dict,
    settings: dict,
    paths: TaskPaths,
    counter: TokenCounter,
    all_chapter_names: list[str] | None = None,
    log=print,
) -> bool:
    """生成单个章节并写入报告：已存在同名章节时原地覆盖，否则追加。"""
    chapter = prompt_def["chapter"]
    output_path = paths.output_path(settings)
    log(f"\n{'=' * 60}")
    log(f"[生成中] {chapter} (第 {index + 1} 章)")

    ref_files = list(prompt_def.get("ref_files", []))
    ref_files += state_chain_refs(paths, index, settings, log=log)

    payload, stats = build_generation_request(
        prompt_def["prompt"], ref_files, paths, settings, counter, log=log
    )
    _print_usage(stats, log=log)

    result = await call_llm(client, payload, settings, log=log)
    if result is None:
        log(f"[中断] {chapter} 生成失败，保留 pending 状态。")
        return False

    try:
        names = all_chapter_names or [chapter]
        if replace_chapter_in_report(
            output_path, chapter, result, names,
            history_keep=settings.get("report_history_keep", 10),
        ):
            log(f"[写入] {chapter} → {output_path.name} (已覆盖旧版本)")
        else:
            append_chapter_to_report(
                output_path, chapter, result,
                history_keep=settings.get("report_history_keep", 10),
            )
            log(f"[写入] {chapter} → {output_path.name}")
        log(f"  [输出] 生成了 {len(result)} 字符 (~{counter.count(result)} tokens)")
    except OSError as e:
        log(f"[写入错误] 无法写入 {output_path}: {e}")
        return False

    save_chapter_history(paths, index, result, log=log)
    print_image_hints(prompt_def, log=log)
    return True


# ==================== 修改流程（候选稿） ====================

def candidate_paths(paths: TaskPaths, index: int) -> tuple[Path, Path]:
    base = paths.candidates_dir
    return base / f"chapter_{index + 1}.md", base / f"chapter_{index + 1}.json"


def list_candidates(paths: TaskPaths) -> list[dict]:
    metas = []
    if paths.candidates_dir.exists():
        for meta_file in sorted(paths.candidates_dir.glob("chapter_*.json")):
            try:
                metas.append(json.loads(meta_file.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    return metas


def diff_preview(old: str, new: str, max_lines: int = 40) -> str:
    diff_lines = list(difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile="当前版本", tofile="候选版本", lineterm="", n=2,
    ))
    if not diff_lines:
        return "（内容无差异）"
    shown = "\n".join(diff_lines[:max_lines])
    if len(diff_lines) > max_lines:
        shown += f"\n... （共 {len(diff_lines)} 行差异，仅展示前 {max_lines} 行）"
    return shown


async def modify_single_chapter(
    client: httpx.AsyncClient,
    index: int,
    prompt_def: dict,
    instruction: str,
    settings: dict,
    paths: TaskPaths,
    all_chapter_names: list[str],
    counter: TokenCounter,
    in_place: bool | None = None,
    log=print,
) -> bool:
    """按指令修改章节。

    默认生成候选稿存入 output/candidates/，由 accept/reject 决定是否替换；
    in_place=True（或 settings.modify_in_place）时直接原地替换（旧行为）。
    """
    chapter = prompt_def["chapter"]
    output_path = paths.output_path(settings)
    if in_place is None:
        in_place = settings.get("modify_in_place", False)

    log(f"\n{'=' * 60}")
    log(f"[修改中] {chapter} (第 {index + 1} 章)")

    existing = parse_report_chapter(output_path, chapter, all_chapter_names)
    if existing is None:
        log(f"[错误] 报告中找不到章节: {chapter}")
        return False
    log(f"  [现有内容] {len(existing)} 字符 (~{counter.count(existing)} tokens)")

    ref_files = list(prompt_def.get("ref_files", []))
    ref_files += state_chain_refs(paths, index, settings, log=log)

    payload, stats = build_generation_request(
        prompt_def["prompt"], ref_files, paths, settings, counter,
        existing_content=existing, instruction=instruction, log=log,
    )
    _print_usage(stats, log=log)

    result = await call_llm(client, payload, settings, log=log)
    if result is None:
        log(f"[中断] {chapter} 修改失败，保留原内容不变。")
        return False

    if in_place:
        if replace_chapter_in_report(
            output_path, chapter, result, all_chapter_names,
            history_keep=settings.get("report_history_keep", 10),
        ):
            log(f"[写入] {chapter} → {output_path.name} (已原地替换)")
            save_chapter_history(paths, index, result, log=log)
            return True
        log("[错误] 替换章节内容失败，保留原内容。")
        return False

    # 候选稿流程
    md_path, meta_path = candidate_paths(paths, index)
    atomic_write_text(md_path, result)
    save_json(meta_path, {
        "index": index,
        "chapter": chapter,
        "instruction": instruction,
        "created": datetime.now().isoformat(timespec="seconds"),
        "chars": len(result),
    })
    log(f"[候选稿] 已保存至 {md_path}（原文未改动）")
    log("\n  ── 差异预览 " + "─" * 40)
    for line in diff_preview(existing, result).splitlines():
        log(f"  {line}")
    log("  " + "─" * 52)
    log(f"  接受: docloom accept {index + 1}    放弃: docloom reject {index + 1}")
    return True


def accept_candidate(paths: TaskPaths, index: int, log=print) -> bool:
    """将候选稿替换进报告，并同步 State Chain 缓存。"""
    settings = load_settings(paths)
    prompts = load_prompts(paths)
    if index < 0 or index >= len(prompts):
        log(f"[错误] 章节编号 {index + 1} 超出范围（共 {len(prompts)} 章）")
        return False
    md_path, meta_path = candidate_paths(paths, index)
    if not md_path.exists():
        log(f"[错误] 第 {index + 1} 章没有待处理的候选稿。")
        return False

    all_names = [p["chapter"] for p in prompts]
    chapter = prompts[index]["chapter"]
    new_content = md_path.read_text(encoding="utf-8")
    output_path = paths.output_path(settings)

    if not replace_chapter_in_report(
        output_path, chapter, new_content, all_names,
        history_keep=settings.get("report_history_keep", 10),
    ):
        log(f"[错误] 报告中找不到章节 {chapter}，无法替换。候选稿保留在 {md_path}")
        return False

    save_chapter_history(paths, index, new_content, log=log)
    md_path.unlink(missing_ok=True)
    meta_path.unlink(missing_ok=True)
    log(f"[接受] 候选稿已替换进报告: {chapter}")
    return True


def reject_candidate(paths: TaskPaths, index: int, log=print) -> bool:
    md_path, meta_path = candidate_paths(paths, index)
    if not md_path.exists():
        log(f"[错误] 第 {index + 1} 章没有待处理的候选稿。")
        return False
    md_path.unlink(missing_ok=True)
    meta_path.unlink(missing_ok=True)
    log(f"[放弃] 第 {index + 1} 章候选稿已删除，报告保持原样。")
    return True


# ==================== 章节结构管理（增 / 删 / 换序） ====================
# task_state.json、状态链缓存 generated_chapter_N.txt、候选稿 chapter_N.*
# 都按章节下标绑定，增删换序必须同步重排，否则状态会错位到别的章上。

def _indexed_files(paths: TaskPaths, index: int) -> list[Path]:
    """与章节下标绑定的全部派生文件（状态链缓存、候选稿正文与元数据）。"""
    md, meta = candidate_paths(paths, index)
    return [paths.processed_dir / f"generated_chapter_{index + 1}.txt", md, meta]


def _rename_index(paths: TaskPaths, src: int, dst: int) -> None:
    for s, d in zip(_indexed_files(paths, src), _indexed_files(paths, dst)):
        if s.exists():
            d.parent.mkdir(parents=True, exist_ok=True)
            s.replace(d)


def _fix_candidate_meta(paths: TaskPaths, index: int) -> None:
    _, meta = candidate_paths(paths, index)
    if meta.exists():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            data["index"] = index
            save_json(meta, data)
        except (OSError, ValueError):
            pass


def add_chapter(paths: TaskPaths, chapter: str, prompt_text: str = "", log=print) -> int:
    """在末尾新增一章（自动 pending），返回新章下标。"""
    prompts = load_prompts(paths)
    prompts.append({"chapter": chapter,
                    "prompt": prompt_text or "请撰写本章内容。",
                    "ref_files": [], "image_hints": []})
    save_json(paths.prompts_path, prompts)
    state = load_task_state(paths, len(prompts))
    state[str(len(prompts) - 1)] = "pending"
    save_task_state(paths, state)
    log(f"[章节] 新增: {chapter}（第 {len(prompts)} 章）")
    return len(prompts) - 1


def delete_chapter(paths: TaskPaths, index: int, log=print) -> bool:
    """删除章节定义并把后续章节的状态/派生文件整体前移一位。

    报告文件中该章已生成的正文不会自动删除（防误删，可手动清理）。
    """
    prompts = load_prompts(paths)
    if index < 0 or index >= len(prompts):
        return False
    old_count = len(prompts)
    removed = prompts.pop(index)
    state = load_task_state(paths, old_count)
    for f in _indexed_files(paths, index):
        f.unlink(missing_ok=True)
    new_state = {}
    for i in range(old_count):
        if i == index:
            continue
        new_i = i if i < index else i - 1
        new_state[str(new_i)] = state.get(str(i), "pending")
        if i > index:
            _rename_index(paths, i, i - 1)
            _fix_candidate_meta(paths, i - 1)
    save_json(paths.prompts_path, prompts)
    save_task_state(paths, new_state)
    log(f"[章节] 已删除定义: {removed['chapter']}（报告中已生成的正文未动）")
    return True


def move_chapter(paths: TaskPaths, index: int, delta: int, log=print) -> bool:
    """交换第 index 章与第 index+delta 章（含状态与派生文件）。

    注意：成品报告里已有内容的先后顺序不会自动调整——重新生成时会按
    章节名原地覆盖。需要成品顺序也变化时 reset-all 重跑或手动剪贴。
    """
    prompts = load_prompts(paths)
    j = index + delta
    if not (0 <= index < len(prompts)) or not (0 <= j < len(prompts)):
        return False
    prompts[index], prompts[j] = prompts[j], prompts[index]
    state = load_task_state(paths, len(prompts))
    state[str(index)], state[str(j)] = (
        state.get(str(j), "pending"), state.get(str(index), "pending"))
    tmp = len(prompts) + 1000  # 经由临时下标三步交换派生文件
    _rename_index(paths, index, tmp)
    _rename_index(paths, j, index)
    _rename_index(paths, tmp, j)
    _fix_candidate_meta(paths, index)
    _fix_candidate_meta(paths, j)
    save_json(paths.prompts_path, prompts)
    save_task_state(paths, state)
    log(f"[章节] 已交换第 {index + 1} 章与第 {j + 1} 章")
    return True


# ==================== 批量运行 ====================

async def run_scheduler(
    paths: TaskPaths, run_index: int | None = None, log=print
) -> bool:
    """核心调度入口：处理所有 pending 章节（或指定单章）。返回是否全部成功。"""
    settings = load_settings(paths)
    prompts = load_prompts(paths)
    state = load_task_state(paths, len(prompts))
    output_path = paths.output_path(settings)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    paths.processed_dir.mkdir(parents=True, exist_ok=True)

    if run_index is not None:
        if run_index < 0 or run_index >= len(prompts):
            log(f"[错误] 章节编号 {run_index + 1} 超出范围（共 {len(prompts)} 章）")
            return False
        pending_indices = [run_index]
        state[str(run_index)] = "pending"
    else:
        pending_indices = [
            i for i in range(len(prompts)) if state.get(str(i)) != "completed"
        ]

    if not pending_indices:
        log("[完成] 所有章节已生成完毕。")
        log("如需重新生成某章: docloom reset N")
        return True

    ctx = settings.get("context_window_tokens", 56000)
    ratio = settings.get("max_input_ratio", 0.75)
    log(f"\n{'=' * 60}")
    log(f"  任务: {paths.name}  |  项目: {settings['project_name']}")
    log(f"  章节: {len(prompts)} 个，待处理 {len(pending_indices)} 个")
    log(f"  模型: {settings['model']}  |  API: {settings['api_url']}")
    log(f"  上下文: {ctx} tokens (输入上限 {int(ctx * ratio)})")
    log(f"{'=' * 60}")

    counter = TokenCounter(settings)
    all_names = [p["chapter"] for p in prompts]
    try:
        async with httpx.AsyncClient() as client:
            for idx in pending_indices:
                prompt_def = prompts[idx]
                success = await process_single_chapter(
                    client, idx, prompt_def, settings, paths, counter,
                    all_chapter_names=all_names, log=log
                )
                if success:
                    state[str(idx)] = "completed"
                    save_task_state(paths, state)
                    log(f"[完成] {prompt_def['chapter']} ✓")
                else:
                    save_task_state(paths, state)
                    log("请检查 API 服务后重新运行: docloom run")
                    return False
    finally:
        counter.close()

    log(f"\n{'=' * 60}")
    log("[全部完成] 报告已生成完毕！")
    log(f"输出文件: {output_path}")
    log("提示: 运行 `docloom hints` 可查看各章节需要的配图/视频清单。")
    return True


async def run_modifications(
    paths: TaskPaths,
    modifications: list[tuple[int, str]],
    custom_refs: list[list[str]] | None = None,
    in_place: bool | None = None,
    dry_run: bool = False,
    mod_state: dict | None = None,
    mod_state_orig_indices: list[int] | None = None,
    log=print,
) -> None:
    """依次执行 (chapter_index, instruction) 修改列表。

    mod_state / mod_state_orig_indices 由 batch-modify 传入以支持断点续传。
    """
    settings = load_settings(paths)
    prompts = load_prompts(paths)
    all_names = [p["chapter"] for p in prompts]
    output_path = paths.output_path(settings)
    custom_refs = list(custom_refs or [])
    while len(custom_refs) < len(modifications):
        custom_refs.append([])

    counter = TokenCounter(settings)
    try:
        async with httpx.AsyncClient() as client:
            for i, (chapter_idx, instruction) in enumerate(modifications):
                prompt_def = dict(prompts[chapter_idx])
                if custom_refs[i]:
                    prompt_def["ref_files"] = custom_refs[i]

                log(f"\n[进度] {i + 1}/{len(modifications)} → {prompt_def['chapter']}")

                if dry_run:
                    existing = parse_report_chapter(
                        output_path, prompt_def["chapter"], all_names)
                    existing_str = (f"{len(existing)} 字符 (~{counter.count(existing)} tokens)"
                                    if existing else "未找到")
                    log(f"  [DRY-RUN] 现有内容: {existing_str}")
                    log(f"  [DRY-RUN] 修改指令: {instruction[:100]}...")
                    log("  [DRY-RUN] 跳过 API 调用。")
                    continue

                success = await modify_single_chapter(
                    client, chapter_idx, prompt_def, instruction,
                    settings, paths, all_names, counter,
                    in_place=in_place, log=log,
                )
                if success and mod_state is not None and mod_state_orig_indices:
                    orig_idx = mod_state_orig_indices[i]
                    mod_state[str(orig_idx)] = "completed"
                    save_json(paths.modification_state_path, mod_state)
                    log(f"  [√] 条目 {orig_idx + 1} 完成（已保存进度）")
                elif success:
                    log(f"  [√] 第 {i + 1} 条修改完成")
                else:
                    log(f"  [×] 第 {i + 1} 条修改失败，继续下一条...")
    finally:
        counter.close()

    log(f"\n{'=' * 60}")
    log("[DRY-RUN 完成（未做任何修改）]" if dry_run else "[修改流程执行完毕]")
    log(f"{'=' * 60}")
