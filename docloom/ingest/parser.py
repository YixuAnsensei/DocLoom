"""PDF/DOCX → 纯文本，输出到任务的 data/processed/。"""

from pathlib import Path

import fitz  # PyMuPDF
from docx import Document

from ..utils import atomic_write_text


def parse_pdf(file_path: Path, log=print) -> str:
    text_parts = []
    try:
        with fitz.open(str(file_path)) as doc:
            for page in doc:
                page_text = page.get_text()
                if page_text:
                    text_parts.append(page_text)
    except Exception as e:
        log(f"[错误] 解析 PDF 失败: {file_path.name} — {e}")
        return ""
    return "\n".join(text_parts)


def parse_docx(file_path: Path, log=print) -> str:
    text_parts = []
    try:
        doc = Document(str(file_path))
        for para in doc.paragraphs:
            if para.text:
                text_parts.append(para.text)
    except Exception as e:
        log(f"[错误] 解析 Word 失败: {file_path.name} — {e}")
        return ""
    return "\n".join(text_parts)


def convert_all(raw_dir: Path, processed_dir: Path, log=print) -> int:
    """转换 raw_dir 下所有 PDF/DOCX 为 txt，返回成功数量。"""
    processed_dir.mkdir(parents=True, exist_ok=True)
    parsers = {".pdf": parse_pdf, ".docx": parse_docx}
    converted = 0

    if not raw_dir.exists():
        log(f"[错误] raw 目录不存在: {raw_dir}")
        log("请先将 PDF 和 Word 文件放入 data/raw/ 目录后再运行。")
        return 0

    for file_path in sorted(raw_dir.iterdir()):
        if not file_path.is_file():
            continue
        suffix = file_path.suffix.lower()
        if suffix not in parsers:
            log(f"[跳过] 不支持的文件格式: {file_path.name}")
            continue

        log(f"[处理中] {file_path.name} ...")
        text_content = parsers[suffix](file_path, log=log)
        if not text_content:
            log(f"[警告] {file_path.name} 提取内容为空，跳过保存。")
            continue

        out_path = processed_dir / (file_path.stem + ".txt")
        try:
            atomic_write_text(out_path, text_content)
            log(f"[完成] {file_path.name} → {out_path.name}")
            converted += 1
        except OSError as e:
            log(f"[错误] 保存 {out_path.name} 失败: {e}")

    log(f"\n===== 全部处理完毕，共转换 {converted} 个文件 =====")
    return converted
