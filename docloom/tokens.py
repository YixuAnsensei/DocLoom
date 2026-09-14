"""token 计数：优先走 llama.cpp-server 的 /tokenize 接口精确计数，
接口不可用（如 Ollama、网络断开）时回退启发式估算。
"""

from urllib.parse import urlsplit

import httpx


def heuristic_tokens(text: str) -> int:
    """启发式估算：中文 ~1.5 token/字，ASCII ~0.3 token/字，其余 ~1.0。误差 ±15%。"""
    chinese = ascii_chars = other = 0
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f" or "\uff00" <= ch <= "\uffef":
            chinese += 1
        elif ord(ch) < 128:
            ascii_chars += 1
        else:
            other += 1
    return int(chinese * 1.5 + ascii_chars * 0.3 + other * 1.0)


def derive_tokenize_url(api_url: str) -> str:
    """从 chat/completions 地址推导同服务的 /tokenize 地址。"""
    parts = urlsplit(api_url)
    return f"{parts.scheme}://{parts.netloc}/tokenize"


class TokenCounter:
    """带自动降级的 token 计数器。

    mode:
      auto      先试 /tokenize，一旦失败本次运行内不再尝试（避免反复超时）
      api       强制接口，失败也回退但每次都重试
      heuristic 只用启发式
    """

    def __init__(self, settings: dict):
        self.mode = settings.get("tokenizer", "auto")
        self.url = settings.get("tokenizer_api_url") or derive_tokenize_url(
            settings.get("api_url", ""))
        self._api_dead = self.mode == "heuristic"
        self._client: httpx.Client | None = None
        self.last_source = "heuristic"

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=10.0)
        return self._client

    def count(self, text: str) -> int:
        if not text:
            return 0
        if not self._api_dead:
            try:
                resp = self._get_client().post(self.url, json={"content": text})
                resp.raise_for_status()
                tokens = resp.json().get("tokens")
                if isinstance(tokens, list):
                    self.last_source = "api"
                    return len(tokens)
            except (httpx.HTTPError, ValueError):
                if self.mode == "auto":
                    self._api_dead = True
        self.last_source = "heuristic"
        return heuristic_tokens(text)

    @property
    def source_label(self) -> str:
        return "精确(/tokenize)" if self.last_source == "api" else "估算(启发式)"

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
