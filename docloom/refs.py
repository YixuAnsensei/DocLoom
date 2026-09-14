"""参考资料装载：文本合并、图片收集、caption 注入、多模态 content 构建。"""

import base64
import mimetypes
from pathlib import Path

from .config import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, TaskPaths
from .utils import load_json


def resolve_ref_path(paths: TaskPaths, fname: str) -> Path | None:
    """安全解析任务内参考资料路径，兼容旧的无目录前缀写法。

    新写法使用相对于 data/ 的路径，如 processed/a.txt、raw/a.pdf、
    extracted_images/paper/page_1.png；旧写法仍按 processed、图片、data 顺序查找。
    """
    requested = Path(fname)
    if requested.is_absolute() or ".." in requested.parts:
        return None
    data_dir = (paths.root / "data").resolve()
    bases = (data_dir,) if requested.parts and requested.parts[0] in {
        "processed", "raw", "extracted_images"
    } else (paths.processed_dir, paths.images_dir, data_dir)
    for base in bases:
        candidate = (base / requested).resolve()
        try:
            candidate.relative_to(data_dir)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None


def list_reference_files(paths: TaskPaths) -> list[dict]:
    """列出可在 ref_files 中选择的任务资料，使用 data/ 相对路径作稳定标识。"""
    data_dir = paths.root / "data"
    allowed = {".txt", ".pdf", ".docx", *IMAGE_EXTENSIONS}
    entries = []
    for base in (paths.processed_dir, paths.raw_dir, paths.images_dir):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in allowed:
                entries.append({
                    "name": path.relative_to(data_dir).as_posix(),
                    "kind": path.suffix.lower().lstrip(".").upper(),
                })
    return sorted(entries, key=lambda item: (item["kind"], item["name"]))


def load_captions(paths: TaskPaths) -> dict:
    """加载 `docloom caption` 生成的图片描述表 {相对路径: 描述文本}。"""
    if paths.captions_path.exists():
        return load_json(paths.captions_path, {})
    return {}


def caption_key(paths: TaskPaths, img_path: Path) -> str:
    """caption 表的键：相对 images_dir（或 data/）的 posix 路径。"""
    for base in (paths.images_dir, paths.processed_dir, paths.root / "data"):
        try:
            return img_path.relative_to(base).as_posix()
        except ValueError:
            continue
    return img_path.name


def split_refs(paths: TaskPaths, ref_files: list[str]) -> tuple[list[str], list[Path]]:
    """把 ref_files 分成 (文本文件名列表, 图片路径列表)。"""
    text_refs: list[str] = []
    image_refs: list[Path] = []
    for fname in ref_files:
        resolved = resolve_ref_path(paths, fname)
        ext = Path(fname).suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            if resolved is not None:
                image_refs.append(resolved)
        else:
            text_refs.append(fname)
    return text_refs, image_refs


def load_ref_content(
    paths: TaskPaths,
    text_refs: list[str],
    image_refs: list[Path],
    settings: dict,
    log=print,
) -> str:
    """读取并合并参考资料文本；纯文本模型下自动注入图片 caption。"""
    parts = []
    found_any = False

    for fname in text_refs:
        ref_path = resolve_ref_path(paths, fname)
        if ref_path is None:
            log(f"  [提示] 参考资料不存在: {fname}，已跳过。")
            continue
        ext = ref_path.suffix.lower()
        if ext in VIDEO_EXTENSIONS:
            log(f"  [提示] {fname} 是视频文件，暂不支持。建议提取关键帧保存为图片后引入。")
            continue
        try:
            content = ref_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            log(f"  [提示] {fname} 无法以 UTF-8 解码（可能是二进制文件），已跳过。")
            continue
        parts.append(f"--- 参考资料: {fname} ---\n{content}")
        found_any = True

    # 视觉模型关闭时，用 caption 让纯文本模型"看到"图片
    if image_refs and not settings.get("vision_model", False):
        captions = load_captions(paths)
        missing = []
        for img in image_refs:
            key = caption_key(paths, img)
            cap = captions.get(key) or captions.get(img.name)
            if cap:
                parts.append(f"--- 图片描述（{key}）---\n{cap}")
                found_any = True
            else:
                missing.append(key)
        if missing:
            log(f"  [提示] {len(missing)} 张图片没有描述且视觉模型未开启，将被忽略: "
                f"{', '.join(missing[:5])}")
            log("         运行 `docloom caption` 可为图片生成文字描述，纯文本模型也能利用图片信息。")

    if not found_any:
        if not text_refs and not image_refs:
            return "（本小节无指定参考资料，请根据该主题的通用知识撰写。）"
        return "（指定的参考资料均未找到，请根据该章节主题结合通用知识撰写。）"

    return "\n\n".join(parts)


def encode_image_to_data_url(file_path: Path) -> str:
    mime_type = mimetypes.guess_type(str(file_path))[0] or "image/png"
    with open(file_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime_type};base64,{b64}"


def build_multimodal_content(
    text: str, image_paths: list[Path], settings: dict, log=print
) -> str | list:
    """构建消息 content：无图或 vision 关闭 → 纯文本；否则 text+image_url 数组。"""
    if not image_paths or not settings.get("vision_model", False):
        return text

    content_parts: list = [{"type": "text", "text": text}]
    for img_path in image_paths:
        try:
            data_url = encode_image_to_data_url(img_path)
            content_parts.append({"type": "image_url", "image_url": {"url": data_url}})
            log(f"  [视觉] 已编码图片: {img_path.name} ({len(data_url)} 字符 base64)")
        except OSError as e:
            log(f"  [警告] 图片编码失败 {img_path.name}: {e}")
    return content_parts


def estimate_image_tokens(image_count: int, settings: dict) -> int:
    if not settings.get("vision_model", False):
        return 0
    return image_count * settings.get("vision_image_tokens", 512)
