"""任务一致性体检：交叉核对 task_state ↔ 报告正文 ↔ 状态链缓存，
发现并（可选）修复三者之间的漂移。

背景：task_state.json 按下标记录 completed/pending，成品报告按章节名保存正文，
状态链缓存 generated_chapter_N.txt 是章节纯文本副本——三者是独立文件。
手动编辑/删除报告、外部改文件、生成中途崩溃，都可能让它们对不上：
最坑的是「state=completed 但报告里没这一章」，run 会直接跳过它，成品静默缺章。
"""

from dataclasses import dataclass, field
from pathlib import Path

from .config import (TaskPaths, load_prompts, load_settings, load_task_state,
                     save_task_state)
from .report import parse_report_chapter
from .utils import atomic_write_text


@dataclass
class ChapterDiag:
    index: int
    chapter: str
    state: str
    has_content: bool
    has_cache: bool
    issues: list[str] = field(default_factory=list)
    fix_state: str | None = None   # 需改写 state 时的目标值
    rebuild_cache: bool = False    # 需从报告正文重建状态链缓存


def _cache_path(paths: TaskPaths, index: int) -> Path:
    return paths.processed_dir / f"generated_chapter_{index + 1}.txt"


def diagnose(paths: TaskPaths) -> list[ChapterDiag]:
    """核对每章的 state / 报告正文 / 状态链缓存，返回逐章诊断。"""
    settings = load_settings(paths)
    prompts = load_prompts(paths)
    state = load_task_state(paths, len(prompts))
    output_path = paths.output_path(settings)
    all_names = [p["chapter"] for p in prompts]
    chain_on = settings.get("state_chain", False)

    diags: list[ChapterDiag] = []
    for i, p in enumerate(prompts):
        chapter = p["chapter"]
        st = state.get(str(i), "pending")
        body = parse_report_chapter(output_path, chapter, all_names)
        has_content = bool(body and body.strip())
        has_cache = _cache_path(paths, i).exists()
        d = ChapterDiag(index=i, chapter=chapter, state=st,
                        has_content=has_content, has_cache=has_cache)

        if st == "completed" and not has_content:
            d.issues.append("状态 completed 但报告中无正文（run 会跳过 → 成品缺这一章）")
            d.fix_state = "pending"
        elif st != "completed" and has_content:
            d.issues.append("报告已有正文但状态 pending（run 会重生成覆盖）")
            d.fix_state = "completed"

        if chain_on and has_content and not has_cache:
            d.issues.append(
                f"缺状态链缓存 generated_chapter_{i + 1}.txt（state_chain 注入会漏这一章）")
            d.rebuild_cache = True

        diags.append(d)
    return diags


def apply_fixes(paths: TaskPaths, diags: list[ChapterDiag], log=print) -> int:
    """按诊断结果对账：改写 state、从报告正文重建状态链缓存。返回修复条数。"""
    settings = load_settings(paths)
    prompts = load_prompts(paths)
    state = load_task_state(paths, len(prompts))
    output_path = paths.output_path(settings)
    all_names = [p["chapter"] for p in prompts]

    fixed = 0
    changed_state = False
    for d in diags:
        if d.fix_state is not None and state.get(str(d.index)) != d.fix_state:
            state[str(d.index)] = d.fix_state
            changed_state = True
            fixed += 1
            log(f"  [修复] 第 {d.index + 1} 章状态 → {d.fix_state}")
        if d.rebuild_cache:
            body = parse_report_chapter(output_path, d.chapter, all_names)
            if body and body.strip():
                atomic_write_text(_cache_path(paths, d.index), body)
                fixed += 1
                log(f"  [修复] 第 {d.index + 1} 章状态链缓存已从报告重建")
    if changed_state:
        save_task_state(paths, state)
    return fixed


def drift_count(paths: TaskPaths) -> int:
    """有多少章存在漂移（供 status 顶部提示用）。"""
    return sum(1 for d in diagnose(paths) if d.issues)
