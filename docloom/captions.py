"""图片描述（caption）流程。

用视觉模型为任务内的图片逐张生成文字描述，存入 data/image_captions.json。
之后即使主模型是纯文本模型，也能通过注入描述文本来"看图"。
支持断点续传（已有描述的图片自动跳过）。
"""

import httpx

from .config import IMAGE_EXTENSIONS, TaskPaths, load_settings
from .llm import call_llm
from .refs import caption_key, encode_image_to_data_url
from .utils import load_json, save_json


def collect_task_images(paths: TaskPaths) -> list:
    """收集任务内所有图片：extracted_images/（递归）+ processed/ + data/ 顶层。"""
    images = []
    if paths.images_dir.exists():
        images += [p for p in sorted(paths.images_dir.rglob("*"))
                   if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    for base in (paths.processed_dir, paths.root / "data"):
        if base.exists():
            images += [p for p in sorted(base.iterdir())
                       if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    return images


async def generate_captions(
    paths: TaskPaths,
    model: str | None = None,
    api_url: str | None = None,
    force: bool = False,
    log=print,
) -> None:
    settings = load_settings(paths)
    caption_settings = dict(settings)
    caption_settings["model"] = model or settings.get("caption_model") or settings["model"]
    caption_settings["api_url"] = (api_url or settings.get("caption_api_url")
                                   or settings["api_url"])
    caption_prompt = settings.get("caption_prompt") or "请简要描述这张图片。"

    images = collect_task_images(paths)
    if not images:
        log("[提示] 任务内没有找到图片。先运行 `docloom extract-images` 从 PDF 提取。")
        return

    captions = load_json(paths.captions_path, {}) if paths.captions_path.exists() else {}
    todo = []
    for img in images:
        key = caption_key(paths, img)
        if force or not captions.get(key):
            todo.append((key, img))

    log(f"\n{'=' * 60}")
    log(f"  图片描述生成  |  模型: {caption_settings['model']}")
    log(f"  共 {len(images)} 张图片，待处理 {len(todo)} 张（已完成的自动跳过）")
    log(f"{'=' * 60}")
    if not todo:
        log("[完成] 所有图片均已有描述。加 --force 可全部重新生成。")
        return

    done = 0
    async with httpx.AsyncClient() as client:
        for key, img in todo:
            log(f"\n[描述中] {key}")
            try:
                data_url = encode_image_to_data_url(img)
            except OSError as e:
                log(f"  [警告] 读取图片失败: {e}")
                continue
            payload = {
                "model": caption_settings["model"],
                "temperature": 0.2,
                "messages": [
                    {"role": "user", "content": [
                        {"type": "text", "text": caption_prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ]},
                ],
            }
            result = await call_llm(client, payload, caption_settings, log=log)
            if result is None:
                log(f"  [跳过] {key} 描述失败，可稍后重跑续传。")
                continue
            captions[key] = result.strip()
            save_json(paths.captions_path, captions)
            done += 1
            log(f"  [√] {key}: {result.strip()[:60]}...")

    log(f"\n[完成] 本次生成 {done}/{len(todo)} 条描述 → {paths.captions_path}")
    log("提示: 在 prompts.json 的 ref_files 中引用图片后，纯文本模型将自动使用这些描述。")
