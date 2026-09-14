"""参考资料截断策略：head / tail / middle / smart。"""

from .tokens import TokenCounter


def _clamp_ratio(ratio: float) -> float:
    return min(max(ratio, 0.05), 0.95)


def _truncate_head(text: str, max_chars: int, keep_ratio: float) -> str:
    """只保留开头。"""
    keep_chars = min(int(len(text) * keep_ratio), max_chars)
    return (
        f"{text[:keep_chars]}\n\n"
        f"... [上下文管理：参考资料过长，保留了开头 {int(keep_ratio * 100)}% 的内容] ..."
    )


def _truncate_tail(text: str, max_chars: int, keep_ratio: float) -> str:
    """只保留结尾。"""
    keep_chars = min(int(len(text) * keep_ratio), max_chars)
    return (
        f"... [上下文管理：参考资料过长，保留了末尾 {int(keep_ratio * 100)}% 的内容] ...\n\n"
        f"{text[-keep_chars:]}"
    )


def _truncate_middle(text: str, max_chars: int, keep_ratio: float) -> str:
    """保留中间，砍掉首尾。"""
    total = len(text)
    cut = int(total * (1 - keep_ratio) / 2)
    mid_text = text[cut:total - cut][:max_chars]
    return (
        f"... [上下文管理：参考资料过长，保留了中间 {int(keep_ratio * 100)}% 的内容] ...\n\n"
        f"{mid_text}\n\n"
        f"... [上下文管理：截断结束] ..."
    )


def _truncate_smart(text: str, max_chars: int, keep_ratio: float) -> str:
    """保留开头为主 + 少量结尾（默认策略）。"""
    total = len(text)
    head_chars = min(int(total * keep_ratio), int(max_chars * 0.8))
    tail_chars = min(int(total * (1 - keep_ratio) * 0.3), max_chars - head_chars)
    head_part = text[:head_chars]
    tail_part = text[-tail_chars:] if tail_chars > 0 else ""
    return (
        f"{head_part}\n\n"
        f"... [上下文管理：参考资料过长，保留了开头与末尾部分内容] ...\n\n"
        f"{tail_part}"
    )


TRUNCATION_STRATEGIES = {
    "head": _truncate_head,
    "tail": _truncate_tail,
    "middle": _truncate_middle,
    "smart": _truncate_smart,
}


def apply_truncation(
    text: str,
    max_tokens: int,
    counter: TokenCounter,
    strategy: str = "smart",
    keep_ratio: float = 0.6,
) -> tuple[str, bool]:
    """统一截断入口，返回 (截断后文本, 是否发生截断)。

    策略函数按字符近似裁剪后，用 counter 复核 token 数；若仍超限，
    按比例继续收缩（最多 4 轮），确保结果真正落在 max_tokens 内。
    """
    if max_tokens <= 0:
        return "", True
    total_tokens = counter.count(text)
    if total_tokens <= max_tokens:
        return text, False

    keep_ratio = _clamp_ratio(keep_ratio)
    # tokens → 近似字符数（中文 ~0.67 字/token，取宽松近似再由复核收敛）
    max_chars = max(int(max_tokens * 2), 200)
    strategy_fn = TRUNCATION_STRATEGIES.get(strategy, _truncate_smart)
    result = strategy_fn(text, max_chars, keep_ratio)

    for _ in range(4):
        result_tokens = counter.count(result)
        if result_tokens <= max_tokens:
            break
        shrink = max_tokens / result_tokens * 0.9
        max_chars = max(int(len(result) * shrink), 100)
        result = strategy_fn(text, max_chars, _clamp_ratio(keep_ratio * shrink))

    result_tokens = counter.count(result)
    if result_tokens > max_tokens:
        # 兜底硬切：4 轮收敛仍超限时按比例直接裁字符，保证绝不超预算
        hard_chars = max(int(len(result) * max_tokens / result_tokens * 0.9), 50)
        result = result[:hard_chars]

    return result, True
