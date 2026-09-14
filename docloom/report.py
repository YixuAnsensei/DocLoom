"""报告文件的章节解析、版本快照与替换（全部原子写入）。"""

from datetime import datetime
from pathlib import Path

from .utils import atomic_write_text


def snapshot_report(report_path: Path, content: str, keep: int) -> Path | None:
    """在改写现有报告前保存快照，并仅保留最近 keep 份。"""
    if keep <= 0:
        return None
    history_dir = report_path.parent / ".history"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    snapshot = history_dir / f"{report_path.stem}_{stamp}{report_path.suffix}"
    atomic_write_text(snapshot, content)
    snapshots = sorted(history_dir.glob(f"{report_path.stem}_*{report_path.suffix}")
                       )
    for obsolete in snapshots[:-keep]:
        obsolete.unlink(missing_ok=True)
    return snapshot


def _find_chapter_span(
    content: str, chapter_name: str, all_names: list[str]
) -> tuple[int, int] | None:
    """定位章节正文在报告中的 [start, end) 区间。

    匹配策略：匹配 `\\n\\n## 名称\\n`（标题后允许无空行，兼容 Marp 紧凑排版）；
    失败且名称含 " — " 时用前缀回退（容错章节名改过、与报告标题不一致的情况）。
    """
    # 统一在开头补 \n\n，使位于文件第一行的章节标题也能命中标记
    padded = "\n\n" + content

    def find_heading(name: str, from_pos: int = 0) -> tuple[int, int]:
        """返回 (标题起点, 正文起点)；未找到返回 (-1, -1)。"""
        marker = f"\n\n## {name}\n"
        pos = padded.find(marker, from_pos)
        if pos == -1:
            return -1, -1
        body = pos + len(marker)
        while body < len(padded) and padded[body] == "\n":
            body += 1
        return pos, body

    start, body_start = find_heading(chapter_name)
    if start == -1 and " — " in chapter_name:
        start, body_start = find_heading(chapter_name.split(" — ")[0])
    if start == -1:
        return None

    next_boundary = len(padded)
    for name in all_names:
        if name == chapter_name:
            continue
        for candidate in {name, name.split(" — ")[0]}:
            pos, _ = find_heading(candidate, body_start)
            if pos != -1 and pos < next_boundary:
                next_boundary = pos
    # 换算回未加前缀的原始 content 坐标
    return max(body_start - 2, 0), max(next_boundary - 2, 0)


def parse_report_chapter(
    report_path: Path, chapter_name: str, all_names: list[str]
) -> str | None:
    """读取报告中指定章节的当前正文；报告不存在或找不到章节时返回 None。"""
    if not report_path.exists():
        return None
    content = report_path.read_text(encoding="utf-8")
    span = _find_chapter_span(content, chapter_name, all_names)
    if span is None:
        return None
    return content[span[0]:span[1]]


def replace_chapter_in_report(
    report_path: Path, chapter_name: str, new_content: str, all_names: list[str],
    history_keep: int = 10,
) -> bool:
    if not report_path.exists():
        return False
    content = report_path.read_text(encoding="utf-8")
    span = _find_chapter_span(content, chapter_name, all_names)
    if span is None:
        return False
    snapshot_report(report_path, content, history_keep)
    atomic_write_text(
        report_path, content[:span[0]] + new_content + content[span[1]:]
    )
    return True


def append_chapter_to_report(
    report_path: Path, chapter_name: str, body: str, history_keep: int = 10,
) -> None:
    existing = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    if existing:
        snapshot_report(report_path, existing, history_keep)
    atomic_write_text(report_path, f"{existing}\n\n## {chapter_name}\n\n{body}\n")
