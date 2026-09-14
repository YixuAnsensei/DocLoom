"""DocLoom 命令行入口。

    docloom new 我的任务 --template report   # 从模板新建任务
    docloom tasks                            # 列出所有任务
    docloom use 我的任务                     # 设为默认任务
    docloom parse                            # data/raw → data/processed
    docloom extract-images                   # 从 PDF 提取图片
    docloom caption                          # 为图片生成文字描述
    docloom review                           # 生成预览文件（含 token 预算）
    docloom run [N]                          # 生成所有 pending 章节（或第 N 章）
    docloom status                           # 章节状态
    docloom modify N -p "修改要求"            # 生成候选稿
    docloom accept N / reject N              # 接受/放弃候选稿
    docloom serve                            # 启动 Web UI
"""

import argparse
import asyncio
import shutil
import sys
from datetime import datetime
from pathlib import Path

from . import __version__

from .config import (TaskPaths, find_workspace_root, list_tasks, load_prompts,
                     load_settings, load_task_state, resolve_task, save_task_state,
                     set_current_task, templates_root)
from .refs import resolve_ref_path
from .utils import LogTee, load_json, make_zip, recent_log_path, save_json


def _task(args) -> TaskPaths:
    ws = find_workspace_root(Path(args.workspace) if args.workspace else None)
    return resolve_task(ws, args.task)


def _missing_extra(extra: str, packages: str) -> None:
    """惰性依赖缺失时给出友好安装提示并退出。"""
    print(f"[缺少可选依赖] 该命令需要 {packages}。")
    print(f'  安装: pip install "docloom[{extra}]"')
    sys.exit(1)


# ==================== 任务管理 ====================

def cmd_new(args) -> None:
    ws = find_workspace_root(Path(args.workspace) if args.workspace else None)
    ws.mkdir(parents=True, exist_ok=True)
    target = ws / args.name
    if target.exists():
        print(f"[错误] 任务已存在: {target}")
        sys.exit(1)

    tpl_root = templates_root()
    template = args.template
    available = sorted(d.name for d in tpl_root.iterdir() if d.is_dir()) if tpl_root.exists() else []
    if template:
        tpl_dir = tpl_root / template
        if not tpl_dir.is_dir():
            print(f"[错误] 模板不存在: {template}。可用模板: {', '.join(available) or '（无）'}")
            sys.exit(1)
        shutil.copytree(tpl_dir, target / "config",
                        ignore=shutil.ignore_patterns("task_state.json", "*.md"))
    else:
        target.joinpath("config").mkdir(parents=True)

    paths = TaskPaths(target)
    paths.ensure_dirs()
    settings = load_settings(paths)      # 补齐默认字段并落盘
    save_json(paths.settings_path, settings)
    prompts = load_prompts(paths)
    save_json(paths.prompts_path, prompts)
    save_task_state(paths, {str(i): "pending" for i in range(len(prompts))})
    set_current_task(ws, args.name)

    print(f"[✓] 任务已创建: {target}")
    print(f"    模板: {template or '（空白，使用默认配置）'}，已设为当前任务。")
    print("  下一步:")
    print("  1. 参考资料放入 data/raw/ 后运行: docloom parse")
    print(f"  2. 编辑章节提示词: {paths.prompts_path}")
    print("  3. 预览确认: docloom review")
    print("  4. 开始生成: docloom run")


def cmd_tasks(args) -> None:
    ws = find_workspace_root(Path(args.workspace) if args.workspace else None)
    tasks = list_tasks(ws)
    current = (ws / ".current").read_text(encoding="utf-8").strip() \
        if (ws / ".current").exists() else None
    if not tasks:
        print(f"workspace 为空（{ws}）。用 `docloom new` 创建任务，或 `docloom templates` 查看模板。")
        return
    print(f"\nworkspace: {ws}")
    for t in tasks:
        settings = load_settings(t)
        prompts = load_prompts(t)
        state = load_task_state(t, len(prompts))
        total = len(prompts)
        done = sum(1 for i in range(total) if state.get(str(i)) == "completed")
        mark = " *" if t.name == current else ""
        filled = round(done / total * 10) if total else 0
        bar = "●" * filled + "○" * (10 - filled)
        active = ""
        if t.state_path.exists():
            active = f"  最近 {datetime.fromtimestamp(t.state_path.stat().st_mtime):%m-%d %H:%M}"
        print(f"  - {t.name}{mark}")
        print(f"      {bar}  {done}/{total} 章  |  {settings['project_name']}{active}")
    if current:
        print("\n(* 为当前默认任务，可用 `docloom use <名称>` 切换)")


def cmd_use(args) -> None:
    ws = find_workspace_root(Path(args.workspace) if args.workspace else None)
    resolve_task(ws, args.name)  # 校验存在
    set_current_task(ws, args.name)
    print(f"[✓] 当前任务已切换为: {args.name}")


def cmd_save_template(args) -> None:
    from .config import export_template
    paths = _task(args)
    try:
        target = export_template(paths, args.name,
                                 description=args.desc or "", force=args.force)
    except FileExistsError as e:
        print(f"[错误] 模板已存在: {e}（加 --force 覆盖）")
        sys.exit(1)
    print(f"[✓] 已导出模板: {target}")
    print(f"    之后可用 `docloom new 新任务 --template {args.name}` 复用这套配置。")


def cmd_templates(_args) -> None:
    tpl_root = templates_root()
    if not tpl_root.exists():
        print("（没有模板目录）")
        return
    print(f"\n可用模板（{tpl_root}）:")
    for d in sorted(tpl_root.iterdir()):
        if not d.is_dir():
            continue
        desc = ""
        desc_file = d / "description.md"
        if desc_file.exists():
            desc = " — " + desc_file.read_text(encoding="utf-8").strip().splitlines()[0]
        print(f"  - {d.name}{desc}")
    print("\n使用: docloom new 我的任务 --template <模板名>")


# ==================== 数据预处理 ====================

def cmd_parse(args) -> None:
    try:
        from .ingest.parser import convert_all
    except ImportError:
        _missing_extra("docs", "pymupdf + python-docx")
        return
    paths = _task(args)
    log = LogTee(paths.root, "parse")
    log(f"任务: {paths.name}")
    convert_all(paths.raw_dir, paths.processed_dir, log=log)


def cmd_extract_images(args) -> None:
    try:
        from .ingest.images import extract_all, extract_images_from_pdf
    except ImportError:
        _missing_extra("docs", "pymupdf")
        return
    paths = _task(args)
    log = LogTee(paths.root, "extract_images")
    paths.images_dir.mkdir(parents=True, exist_ok=True)
    log(f"任务: {paths.name}  |  输出目录: {paths.images_dir}")
    log(f"过滤尺寸: 宽 >= {args.min_width}px, 高 >= {args.min_height}px")
    if args.file:
        pdf_path = Path(args.file).resolve()
        extract_images_from_pdf(pdf_path, paths.images_dir,
                                args.min_width, args.min_height, log=log)
    else:
        extract_all(paths.raw_dir, paths.images_dir,
                    args.min_width, args.min_height, log=log)


def cmd_caption(args) -> None:
    from .captions import generate_captions
    paths = _task(args)
    asyncio.run(generate_captions(paths, model=args.model,
                                  api_url=args.api_url, force=args.force,
                                  log=LogTee(paths.root, "caption")))


# ==================== 生成与状态 ====================

def cmd_run(args) -> None:
    from .pipeline import run_scheduler
    paths = _task(args)
    run_index = args.chapter - 1 if args.chapter else None
    asyncio.run(run_scheduler(paths, run_index=run_index,
                              log=LogTee(paths.root, "run")))


def cmd_status(args) -> None:
    from .doctor import diagnose
    from .pipeline import list_candidates
    paths = _task(args)
    settings = load_settings(paths)
    prompts = load_prompts(paths)
    state = load_task_state(paths, len(prompts))
    save_task_state(paths, state)
    candidates = {c["index"] for c in list_candidates(paths)}

    print(f"\n{'=' * 60}")
    print(f"  任务: {paths.name}  |  {settings['project_name']}（共 {len(prompts)} 章）")
    print(f"{'=' * 60}")
    drift = [d for d in diagnose(paths) if d.issues]
    if drift:
        print(f"  [!] {len(drift)} 章存在 state/报告漂移，详情/修复: docloom doctor --fix")
    for i, p in enumerate(prompts):
        status = state.get(str(i), "pending")
        icon = "✓" if status == "completed" else "○"
        refs = p.get("ref_files", [])
        ref = f" [参考: {', '.join(refs)}]" if refs else ""
        cand = "  ← 有待处理候选稿(accept/reject)" if i in candidates else ""
        print(f"  [{icon}] {i + 1}. {p['chapter']}  [{status}]{ref}{cand}")
    print(f"{'=' * 60}")


def cmd_review(args) -> None:
    from .review import generate_review
    paths = _task(args)
    generate_review(paths, log=LogTee(paths.root, "review"))


def cmd_export(args) -> None:
    paths = _task(args)
    settings = load_settings(paths)
    output_path = paths.output_path(settings)
    if not output_path.exists():
        print(f"[错误] 报告文件不存在: {output_path}，请先运行 docloom run。")
        sys.exit(1)

    archive = Path(args.output) if args.output else (
        paths.root / "output" / f"export_{paths.name}_{datetime.now():%Y%m%d_%H%M%S}.zip"
    )
    if archive.resolve() == output_path.resolve():
        print("[错误] 导出 ZIP 不能覆盖报告文件。")
        sys.exit(1)

    files: dict[str, Path] = {f"output/{output_path.name}": output_path}
    if paths.review_path.exists():
        files["output/review_preview.md"] = paths.review_path
    for prompt in load_prompts(paths):
        for ref in prompt.get("ref_files", []):
            path = resolve_ref_path(paths, ref)
            if path is None:
                print(f"  ! 跳过不存在的参考资料: {ref}")
                continue
            files[path.relative_to(paths.root).as_posix()] = path

    print(f"\n导出任务「{paths.name}」→ {archive}")
    if make_zip(archive, files, log=print):
        print(f"[完成] {archive}")
    else:
        sys.exit(1)


def cmd_logs(args) -> None:
    paths = _task(args)
    path = recent_log_path(paths.root)
    if path is None:
        print("（还没有运行日志）")
        return
    print(f"最近日志: {path}")
    print(path.read_text(encoding="utf-8"), end="")


def cmd_validate(args) -> None:
    from .validate import validate_task
    paths = _task(args)
    errors, warnings = validate_task(paths)
    for message in warnings:
        print(f"[警告] {message}")
    for message in errors:
        print(f"[错误] {message}")
    if errors:
        print(f"[失败] 校验发现 {len(errors)} 个错误、{len(warnings)} 个警告。")
        sys.exit(1)
    print(f"[通过] 任务「{paths.name}」配置有效"
          + (f"（{len(warnings)} 个警告）" if warnings else "。"))


def cmd_doctor(args) -> None:
    from .doctor import apply_fixes, diagnose
    paths = _task(args)
    diags = diagnose(paths)
    problems = [d for d in diags if d.issues]
    print(f"\n{'=' * 60}")
    print(f"  一致性体检: {paths.name}（共 {len(diags)} 章）")
    print(f"{'=' * 60}")
    if not problems:
        print("  [OK] state / 报告正文 / 状态链缓存 三者一致，未发现漂移。")
        return
    for d in problems:
        print(f"\n  [!] 第 {d.index + 1} 章「{d.chapter}」")
        for msg in d.issues:
            print(f"      - {msg}")
    print(f"\n  共 {len(problems)} 章存在漂移。")
    if args.fix:
        print("  ── 开始修复 " + "─" * 30)
        n = apply_fixes(paths, diags, log=print)
        print(f"  [完成] 已修复 {n} 处。若有章节被改回 pending，跑 docloom run 补齐。")
    else:
        print("  加 --fix 自动对账修复：docloom doctor --fix")



def cmd_hints(args) -> None:
    paths = _task(args)
    prompts = load_prompts(paths)
    print(f"\n{'=' * 60}")
    print(f"  配图/视频素材清单（{len(prompts)} 章）")
    print(f"{'=' * 60}")
    total = 0
    for i, p in enumerate(prompts):
        hints = p.get("image_hints", [])
        print(f"\n  [{i + 1}] {p['chapter']}")
        if hints:
            for j, h in enumerate(hints, 1):
                print(f"      {j}. {h}")
            total += len(hints)
        else:
            print("      （无特定建议）")
    print(f"\n  共计 {total} 处配图/视频建议。")


def cmd_reset(args) -> None:
    paths = _task(args)
    prompts = load_prompts(paths)
    state = load_task_state(paths, len(prompts))
    idx = args.chapter - 1
    if idx < 0 or idx >= len(prompts):
        print(f"[错误] 章节编号 {args.chapter} 超出范围（共 {len(prompts)} 章）")
        return
    state[str(idx)] = "pending"
    save_task_state(paths, state)
    print(f"[重置] {args.chapter}. {prompts[idx]['chapter']} → pending")
    if args.prompt:
        prompts[idx]["prompt"] = args.prompt
        save_json(paths.prompts_path, prompts)
        print("[更新] 提示词已更新。")
    history = paths.processed_dir / f"generated_chapter_{args.chapter}.txt"
    if history.exists():
        history.unlink()
        print(f"[清除] 已删除上下文历史文件: {history.name}")


def cmd_reset_all(args) -> None:
    paths = _task(args)
    prompts = load_prompts(paths)
    save_task_state(paths, {str(i): "pending" for i in range(len(prompts))})
    print(f"[重置] 全部 {len(prompts)} 个章节已重置为 pending。")
    deleted = 0
    if paths.processed_dir.exists():
        for f in paths.processed_dir.glob("generated_chapter_*.txt"):
            f.unlink()
            deleted += 1
    if deleted:
        print(f"[清除] 已清空 {deleted} 个上下文历史缓存文件。")


# ==================== 修改流程 ====================

def cmd_modify(args) -> None:
    from .pipeline import run_modifications
    paths = _task(args)
    if len(args.chapter) != len(args.prompt):
        print("[错误] --modify 的章节数必须与 -p/--prompt 数量一致。")
        print('用法: docloom modify 1 -p "修改建议1" （可多次: modify 1 2 -p "建议1" -p "建议2"）')
        return
    settings = load_settings(paths)
    output_path = paths.output_path(settings)
    if not args.dry_run and not output_path.exists():
        print(f"[错误] 报告文件不存在: {output_path}，请先运行 docloom run。")
        return
    modifications = [(n - 1, p) for n, p in zip(args.chapter, args.prompt)]
    asyncio.run(run_modifications(
        paths, modifications, custom_refs=args.ref,
        in_place=True if args.in_place else None, dry_run=args.dry_run,
        log=LogTee(paths.root, "modify"),
    ))


def cmd_batch_modify(args) -> None:
    from .pipeline import run_modifications
    paths = _task(args)
    mods_path = paths.modifications_path
    if not mods_path.exists():
        save_json(mods_path, [{
            "chapter_index": 0,
            "instruction": "请在此处填写对该章节的修改要求（例如：在开头增加一段背景介绍）",
        }])
        print(f"[初始化] 已创建批量修改模板: {mods_path}")
        print("请编辑该文件后重新运行 batch-modify")
        return

    modifications_raw = load_json(mods_path, [])
    all_entries = [(m.get("chapter_index", -1), m.get("instruction", ""))
                   for m in modifications_raw
                   if m.get("chapter_index", -1) >= 0 and m.get("instruction", "").strip()]
    if not all_entries:
        print("[错误] modifications.json 中没有有效的修改条目。")
        return

    mod_state = load_json(paths.modification_state_path, {})
    if mod_state and max(int(k) for k in mod_state) >= len(all_entries):
        print("[提示] modifications.json 条目数已变化，重置修改进度。")
        mod_state = {}
        save_json(paths.modification_state_path, mod_state)

    pending, orig_indices = [], []
    for i, entry in enumerate(all_entries):
        if mod_state.get(str(i)) != "completed":
            pending.append(entry)
            orig_indices.append(i)
    if not pending:
        print("[完成] 所有修改条目均已执行完毕。")
        print("如需重新执行: docloom reset-modifications")
        return

    print(f"共 {len(all_entries)} 条指令，已完成 {len(all_entries) - len(pending)}，"
          f"待处理 {len(pending)}（中断后可续传）")
    asyncio.run(run_modifications(
        paths, pending, dry_run=args.dry_run,
        in_place=True if args.in_place else None,
        mod_state=mod_state, mod_state_orig_indices=orig_indices,
        log=LogTee(paths.root, "batch_modify"),
    ))
    if not args.dry_run:
        remaining = sum(1 for i in range(len(all_entries))
                        if mod_state.get(str(i)) != "completed")
        if remaining == 0:
            paths.modification_state_path.unlink(missing_ok=True)
            print("[清理] 所有条目完成，已清除修改进度记录。")


def cmd_reset_modifications(args) -> None:
    paths = _task(args)
    if paths.modification_state_path.exists():
        paths.modification_state_path.unlink()
        print("[已清除] 批量修改进度已重置。")
    else:
        print("[提示] 没有找到批量修改进度文件，无需重置。")


def cmd_accept(args) -> None:
    from .pipeline import accept_candidate
    accept_candidate(_task(args), args.chapter - 1)


def cmd_reject(args) -> None:
    from .pipeline import reject_candidate
    reject_candidate(_task(args), args.chapter - 1)


def cmd_candidates(args) -> None:
    from .pipeline import list_candidates
    metas = list_candidates(_task(args))
    if not metas:
        print("（没有待处理的候选稿）")
        return
    print(f"\n待处理候选稿 {len(metas)} 份:")
    for m in metas:
        print(f"  [{m['index'] + 1}] {m['chapter']}  ({m['chars']} 字符, {m['created']})")
        print(f"      修改要求: {m['instruction'][:80]}")
    print("\n接受: docloom accept N    放弃: docloom reject N")


# ==================== 联网检索 ====================

def cmd_research(args) -> None:
    from .research import run_research
    paths = _task(args)
    chapter_index = args.chapter - 1 if args.chapter is not None else None
    if not args.query and chapter_index is None:
        print("[错误] 请提供检索词，或用 --chapter N 让模型从该章提示词自动生成检索词。")
        print('用法: docloom research "OpenHarmony 分布式软总线" "softbus architecture"')
        print("      docloom research --chapter 3")
        return
    asyncio.run(run_research(
        paths, queries=args.query or None, chapter_index=chapter_index,
        name=args.name or "", digest=False if args.no_digest else None,
        log=LogTee(paths.root, "research"),
    ))


# ==================== Web UI ====================

def cmd_serve(args) -> None:
    try:
        import uvicorn
        from .webapp.server import create_app
    except ImportError:
        _missing_extra("web", "fastapi + uvicorn")
        return
    ws = find_workspace_root(Path(args.workspace) if args.workspace else None)
    ws.mkdir(parents=True, exist_ok=True)
    app = create_app(ws)
    print(f"\n  DocLoom Web UI  →  http://{args.host}:{args.port}")
    print(f"  workspace: {ws}\n")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


# ==================== argparse ====================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docloom",
        description="DocLoom — 本地大模型长文档自动化生成框架（引擎 + 任务模板分离）",
    )
    parser.add_argument("--workspace", "-w", help="workspace 目录（默认自动向上查找）")
    parser.add_argument("--version", "-V", action="version",
                        version=f"docloom {__version__}")
    sub = parser.add_subparsers(dest="command")

    def add(name, fn, help_text, **kwargs):
        p = sub.add_parser(name, help=help_text, **kwargs)
        p.add_argument("--task", "-t", help="任务名（默认当前任务）")
        p.set_defaults(fn=fn)
        return p

    p = add("new", cmd_new, "从模板新建任务")
    p.add_argument("name", help="任务名（将创建 workspace/<name>/）")
    p.add_argument("--template", help="模板名（docloom templates 查看）")

    add("tasks", cmd_tasks, "列出所有任务")
    p = add("use", cmd_use, "设置当前默认任务")
    p.add_argument("name")
    add("templates", cmd_templates, "列出可用模板")
    p = add("save-template", cmd_save_template, "把当前任务的配置导出为可复用模板")
    p.add_argument("name", help="模板名（将写入 templates/<name>/）")
    p.add_argument("--desc", help="模板一句话描述（description.md）")
    p.add_argument("--force", action="store_true", help="覆盖同名模板")

    p = add("export", cmd_export, "把报告+图片+参考导出为单 .zip")
    p.add_argument("--output", "-o", help="输出 .zip 路径（默认在 output/ 下按时间戳命名）")

    add("parse", cmd_parse, "解析 data/raw 下的 PDF/DOCX 为纯文本")
    p = add("extract-images", cmd_extract_images, "从 PDF 提取嵌入图片")
    p.add_argument("--file", "-f", help="指定单个 PDF（默认处理 data/raw 全部）")
    p.add_argument("--min-width", type=int, default=100)
    p.add_argument("--min-height", type=int, default=100)

    p = add("caption", cmd_caption, "用视觉模型为任务内图片生成文字描述")
    p.add_argument("--model", help="视觉模型名（默认 settings.caption_model 或主模型）")
    p.add_argument("--api-url", help="视觉模型 API（默认 settings.caption_api_url 或主 API）")
    p.add_argument("--force", action="store_true", help="重新生成所有描述")

    p = add("run", cmd_run, "生成所有 pending 章节（或指定章节）")
    p.add_argument("chapter", type=int, nargs="?", help="仅运行第 N 章（1-based）")

    add("status", cmd_status, "列出章节状态")
    add("logs", cmd_logs, "显示最近一次运行日志")
    add("validate", cmd_validate, "静态检查任务配置与参考资料")
    p = add("doctor", cmd_doctor, "体检 state/报告/状态链缓存一致性（--fix 自动对账修复）")
    p.add_argument("--fix", action="store_true", help="自动对账修复发现的漂移")
    add("review", cmd_review, "生成 review 预览文件（含 token 预算）")
    add("hints", cmd_hints, "查看配图/视频建议清单")

    p = add("reset", cmd_reset, "重置第 N 章为 pending")
    p.add_argument("chapter", type=int)
    p.add_argument("--prompt", "-p", help="同时更新该章提示词")
    add("reset-all", cmd_reset_all, "全部章节重置为 pending")

    p = add("modify", cmd_modify, "按指令修改章节（默认生成候选稿）")
    p.add_argument("chapter", type=int, nargs="+", help="章节编号（可多个）")
    p.add_argument("--prompt", "-p", action="append", required=True,
                   help="修改要求（与章节一一对应，可重复）")
    p.add_argument("--ref", nargs="*", action="append",
                   help="临时指定参考资料（覆盖 prompts.json）")
    p.add_argument("--in-place", action="store_true", help="直接原地替换（旧行为）")
    p.add_argument("--dry-run", action="store_true", help="只预览不发请求")

    p = add("batch-modify", cmd_batch_modify, "批量修改（读取 config/modifications.json）")
    p.add_argument("--in-place", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    add("reset-modifications", cmd_reset_modifications, "清除批量修改进度")

    p = add("accept", cmd_accept, "接受候选稿，替换进报告")
    p.add_argument("chapter", type=int)
    p = add("reject", cmd_reject, "放弃候选稿")
    p.add_argument("chapter", type=int)
    add("candidates", cmd_candidates, "列出待处理候选稿")

    p = add("research", cmd_research, "联网检索资料并存为参考文件（data/processed/web_*.txt）")
    p.add_argument("query", nargs="*", help="检索词（可多个；留空时配合 --chapter 自动生成）")
    p.add_argument("--chapter", "-c", type=int,
                   help="从第 N 章的提示词自动生成检索词（1-based）")
    p.add_argument("--name", help="输出文件名片段（默认取检索词/章节名）")
    p.add_argument("--no-digest", action="store_true",
                   help="不用模型提炼，直接保存网页原文截断")

    p = add("serve", cmd_serve, "启动 Web UI")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8600)

    return parser


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return
    args.fn(args)


if __name__ == "__main__":
    main()
