"""任务配置的静态校验。"""

import json
from pathlib import Path

from .config import DEFAULT_SETTINGS, TaskPaths
from .refs import resolve_ref_path


def _read_json(path: Path, label: str, errors: list[str]):
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        errors.append(f"缺少 {label}: {path}")
    except json.JSONDecodeError as e:
        errors.append(f"{label} 不是合法 JSON（第 {e.lineno} 行，第 {e.colno} 列）")
    return None


def validate_task(paths: TaskPaths) -> tuple[list[str], list[str]]:
    """返回 (错误, 警告)，不写入、不补默认配置。"""
    errors: list[str] = []
    warnings: list[str] = []
    settings = _read_json(paths.settings_path, "settings.json", errors)
    prompts = _read_json(paths.prompts_path, "prompts.json", errors)
    if settings is not None:
        if not isinstance(settings, dict):
            errors.append("settings.json 顶层必须是对象")
        else:
            for key in ("model", "api_url", "output_file", "system_prompt"):
                if not str(settings.get(key, "")).strip():
                    errors.append(f"settings.json 缺少有效的 {key}")
            for key in ("temperature", "max_input_ratio", "truncation_keep_ratio"):
                value = settings.get(key, DEFAULT_SETTINGS[key])
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    errors.append(f"settings.json 的 {key} 必须是数字")
            for key in ("context_window_tokens", "state_chain_limit"):
                value = settings.get(key, DEFAULT_SETTINGS[key])
                if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                    errors.append(f"settings.json 的 {key} 必须是大于 0 的整数")
            if settings.get("search_provider", "auto") not in ("auto", "bing", "duckduckgo", "searxng"):
                errors.append("settings.json 的 search_provider 必须是 auto / bing / duckduckgo / searxng")
            unknown = [key for key in settings if key not in DEFAULT_SETTINGS and not key.startswith("_")]
            if unknown:
                warnings.append("未识别 settings 字段: " + ", ".join(unknown))
    if prompts is not None:
        if not isinstance(prompts, list):
            errors.append("prompts.json 顶层必须是章节数组")
        elif not prompts:
            errors.append("prompts.json 至少需要一个章节")
        else:
            titles: set[str] = set()
            for index, prompt in enumerate(prompts, 1):
                prefix = f"第 {index} 章"
                if not isinstance(prompt, dict):
                    errors.append(f"{prefix} 必须是对象")
                    continue
                chapter = prompt.get("chapter")
                content = prompt.get("prompt")
                if not isinstance(chapter, str) or not chapter.strip():
                    errors.append(f"{prefix} 缺少有效的 chapter 标题")
                elif chapter in titles:
                    errors.append(f"{prefix} 的 chapter 标题重复: {chapter}")
                else:
                    titles.add(chapter)
                if not isinstance(content, str) or not content.strip():
                    errors.append(f"{prefix} 缺少有效的 prompt")
                for field in ("ref_files", "image_hints"):
                    if field in prompt and not isinstance(prompt[field], list):
                        errors.append(f"{prefix} 的 {field} 必须是数组")
                refs = prompt.get("ref_files", [])
                if isinstance(refs, list):
                    for ref in refs:
                        if not isinstance(ref, str) or not ref.strip():
                            errors.append(f"{prefix} 的 ref_files 含无效文件名")
                        elif resolve_ref_path(paths, ref) is None:
                            warnings.append(f"{prefix} 的参考资料不存在: {ref}")
    return errors, warnings
