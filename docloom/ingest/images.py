"""从 PDF 提取嵌入图片，输出到任务的 data/extracted_images/<PDF名>/。"""

from pathlib import Path

import fitz  # PyMuPDF


def extract_images_from_pdf(
    pdf_path: Path, out_dir: Path, min_w: int = 100, min_h: int = 100, log=print
) -> int:
    """提取单个 PDF 中的图片（尺寸过滤），返回提取数量。"""
    if not pdf_path.exists():
        log(f"[错误] 文件不存在: {pdf_path}")
        return 0

    target_dir = out_dir / pdf_path.stem
    target_dir.mkdir(parents=True, exist_ok=True)
    extracted = 0

    try:
        with fitz.open(str(pdf_path)) as doc:
            log(f"[处理中] {pdf_path.name} (共 {len(doc)} 页) ...")
            for page_num in range(len(doc)):
                for img_idx, img_info in enumerate(doc[page_num].get_images(full=True), start=1):
                    xref = img_info[0]
                    try:
                        base_image = doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        image_ext = base_image["ext"]
                        width = base_image.get("width", 0)
                        height = base_image.get("height", 0)
                        if width == 0 or height == 0:
                            pix = fitz.Pixmap(doc, xref)
                            width, height = pix.width, pix.height
                            pix = None
                        if width < min_w or height < min_h:
                            continue
                        out_path = target_dir / f"page_{page_num + 1}_img_{img_idx}.{image_ext}"
                        out_path.write_bytes(image_bytes)
                        log(f"  - 页面 {page_num + 1}: 提取图片 {out_path.name} ({width}x{height})")
                        extracted += 1
                    except Exception as img_err:
                        log(f"  [警告] 页面 {page_num + 1} 提取第 {img_idx} 张图片失败: {img_err}")
    except Exception as e:
        log(f"[错误] 解析 PDF 失败: {pdf_path.name} — {e}")
        return 0

    if extracted > 0:
        log(f"[完成] {pdf_path.name}: 提取 {extracted} 张图片 → {target_dir}\n")
    else:
        log(f"[完成] {pdf_path.name}: 未提取到满足尺寸要求的图片。\n")
        try:
            if target_dir.exists() and not any(target_dir.iterdir()):
                target_dir.rmdir()
        except OSError:
            pass
    return extracted


def extract_all(
    raw_dir: Path, out_dir: Path, min_w: int = 100, min_h: int = 100, log=print
) -> int:
    """提取 raw_dir 下所有 PDF 的图片。"""
    if not raw_dir.exists():
        log(f"[错误] raw 目录不存在: {raw_dir}")
        return 0
    pdf_files = sorted(f for f in raw_dir.iterdir()
                       if f.is_file() and f.suffix.lower() == ".pdf")
    if not pdf_files:
        log(f"[提示] {raw_dir} 目录下没有找到任何 PDF 文件。")
        return 0

    log(f"共发现 {len(pdf_files)} 个 PDF 文件，准备开始批量提取...\n")
    total = 0
    for pdf_path in pdf_files:
        total += extract_images_from_pdf(pdf_path, out_dir, min_w, min_h, log=log)
    log(f"===== 运行完毕，共提取保存了 {total} 张图片 =====")
    return total
