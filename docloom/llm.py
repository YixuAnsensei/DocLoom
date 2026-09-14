"""LLM API 调用与 Payload 组装。"""

import asyncio

import httpx

from .config import TaskPaths
from .refs import (build_multimodal_content, estimate_image_tokens,
                   load_ref_content, split_refs)
from .tokens import TokenCounter
from .truncation import apply_truncation
from .utils import strip_think


async def call_llm(
    client: httpx.AsyncClient, payload: dict, settings: dict, log=print
) -> str | None:
    """异步调用 OpenAI 兼容接口，指数退避重试。成功返回 content（已剥离思维链）。"""
    max_retries = settings.get("max_retries", 3)
    timeout = settings.get("request_timeout", 600)
    api_url = settings["api_url"]

    for attempt in range(1, max_retries + 1):
        try:
            log(f"  [请求] 第 {attempt} 次尝试 ...")
            response = await client.post(api_url, json=payload, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            choice = data["choices"][0]
            message = choice["message"]
            content = strip_think(message.get("content") or "")
            if not content.strip():
                # 思考型模型（Qwen3 等）把额度耗在思维链上时正文为空，空章节不能算成功
                reasoning_chars = len(message.get("reasoning_content") or "")
                if choice.get("finish_reason") == "length":
                    log(f"  [空回复] 输出额度耗尽（finish_reason=length），"
                        f"思维链占用了 ~{reasoning_chars} 字符。")
                    log("  提示: 调大 settings.max_output_tokens（或设为 null 不限制），"
                        "或在 settings 里设 \"enable_thinking\": false 关闭思考模式。")
                    return None  # 重试只会同样耗尽，直接放弃
                log("  [空回复] 模型返回了空正文，按失败处理。")
                raise ValueError("empty content")
            log(f"  [成功] 获取回复，长度: {len(content)} 字符")
            return content
        except httpx.TimeoutException:
            log(f"  [超时] 第 {attempt} 次请求超时（{timeout}s）")
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            body = e.response.text[:200].replace("\n", " ")
            log(f"  [HTTP错误] 第 {attempt} 次: {status} {body}")
            if 400 <= status < 500 and status != 429:
                # 客户端错误（参数/模型名错等）重试也不会变好，直接放弃
                log("  [放弃] 4xx 属于请求本身的问题，请检查 settings 的 model/api_url/参数。")
                return None
        except (httpx.RequestError, KeyError, IndexError, ValueError) as e:
            log(f"  [请求异常] 第 {attempt} 次: {e}")

        if attempt < max_retries:
            wait_seconds = min(2 ** attempt, 60)
            log(f"  [等待] {wait_seconds} 秒后重试 ...")
            await asyncio.sleep(wait_seconds)

    log(f"  [失败] 已重试 {max_retries} 次，放弃该任务。")
    return None


def base_payload(settings: dict, user_content) -> dict:
    payload = {
        "model": settings["model"],
        "temperature": settings["temperature"],
        "messages": [
            {"role": "system", "content": settings["system_prompt"]},
            {"role": "user", "content": user_content},
        ],
    }
    if settings.get("max_output_tokens"):
        payload["max_tokens"] = settings["max_output_tokens"]
    # 思考开关：true/false 显式控制（llama.cpp 的 Qwen3 系用 chat_template_kwargs），
    # null 保持服务器默认
    if settings.get("enable_thinking") is not None:
        payload.setdefault("chat_template_kwargs", {})["enable_thinking"] = \
            bool(settings["enable_thinking"])
    # 任意额外请求参数透传（top_p、repeat_penalty、其他后端的思考开关…），
    # 与默认字段冲突时以 extra_payload 为准
    extra = settings.get("extra_payload")
    if isinstance(extra, dict):
        for k, v in extra.items():
            if k == "chat_template_kwargs" and isinstance(v, dict):
                payload.setdefault("chat_template_kwargs", {}).update(v)
            else:
                payload[k] = v
    return payload


def build_generation_request(
    prompt_def_prompt: str,
    ref_files: list[str],
    paths: TaskPaths,
    settings: dict,
    counter: TokenCounter,
    existing_content: str | None = None,
    instruction: str | None = None,
    log=print,
) -> tuple[dict, dict]:
    """组装生成/修改请求，含上下文窗口管理 + 多模态。

    - 生成模式：existing_content 与 instruction 为 None，prompt_def_prompt 作为章节指令。
    - 修改模式：传入现有章节内容与修改指令，参考资料同样参与并接受截断。

    返回 (payload, stats)。
    """
    context_window = settings.get("context_window_tokens", 56000)
    max_input_ratio = settings.get("max_input_ratio", 0.75)
    strategy = settings.get("truncation_strategy", "smart")
    keep_ratio = settings.get("truncation_keep_ratio", 0.6)
    max_input_tokens = int(context_window * max_input_ratio)
    system_prompt = settings["system_prompt"]

    text_refs, image_refs = split_refs(paths, ref_files)
    ref_content = load_ref_content(paths, text_refs, image_refs, settings, log=log)

    img_token_cost = estimate_image_tokens(len(image_refs), settings)
    system_tokens = counter.count(system_prompt)

    if instruction is not None:
        instruction_part = (
            "请根据以下要求对上述章节内容进行修改，保持整体结构和风格不变，"
            f"只做局部调整：\n\n{instruction}"
        )
        fixed_parts_tokens = (
            counter.count(existing_content or "") + counter.count(instruction_part)
        )
    else:
        instruction_part = ""
        fixed_parts_tokens = counter.count(prompt_def_prompt)

    overhead = system_tokens + fixed_parts_tokens + img_token_cost + 300
    ref_available = max_input_tokens - overhead
    ref_original_tokens = counter.count(ref_content)

    was_truncated = False
    if ref_original_tokens > ref_available and ref_available > 0:
        ref_content, was_truncated = apply_truncation(
            ref_content, ref_available, counter, strategy, keep_ratio
        )
        log(f"  [上下文] 参考资料 {ref_original_tokens} tokens → "
            f"截断至约 {counter.count(ref_content)} tokens "
            f"(窗口 {context_window}, 上限 {max_input_tokens})")

    if instruction is not None:
        ref_section = f"\n\n参考资料：\n{ref_content}" if ref_content.strip() else ""
        if image_refs:
            ref_section += f"\n\n（附 {len(image_refs)} 张参考图片）"
        user_message = (
            f"以下是已生成的章节内容：\n\n{existing_content}"
            f"{ref_section}\n\n{instruction_part}"
        )
    else:
        user_message = f"{prompt_def_prompt}\n\n参考资料如下：\n{ref_content}"
        if image_refs:
            user_message += f"\n\n（附 {len(image_refs)} 张参考图片）"

    total_input_tokens = counter.count(user_message) + system_tokens + img_token_cost + 200
    user_content = build_multimodal_content(user_message, image_refs, settings, log=log)
    payload = base_payload(settings, user_content)

    stats = {
        "context_window": context_window,
        "max_input": max_input_tokens,
        "total_input": total_input_tokens,
        "system_tokens": system_tokens,
        "ref_original_tokens": ref_original_tokens,
        "ref_final_tokens": counter.count(ref_content),
        "truncated": was_truncated,
        "usage_pct": round(total_input_tokens / context_window * 100, 1),
        "image_count": len(image_refs),
        "image_tokens": img_token_cost,
        "token_source": counter.source_label,
    }
    return payload, stats
