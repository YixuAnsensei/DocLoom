"""联网检索（web research）：搜索 → 抓取网页正文 → （可选）本地模型提炼，
最终落盘为 data/processed/web_*.txt，与 ref_files 机制无缝衔接。

搜索源无需任何 API key：
  bing        cn.bing.com 结果页解析（大陆网络可用）
  duckduckgo  html.duckduckgo.com 轻量端点
  searxng     自建/公共 SearXNG 实例的 JSON API（settings.searxng_url）
  auto        依次尝试 bing → duckduckgo，成功即止
"""

import asyncio
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from .config import TaskPaths, load_settings
from .llm import base_payload, call_llm
from .utils import atomic_write_text

UA_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
}


def slugify(text: str, max_len: int = 40) -> str:
    """检索词 → 安全文件名片段（保留中英文数字，其余归并为下划线）。"""
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", text).strip("_")
    return s[:max_len] or "research"


# ==================== 网页正文提取 ====================

def extract_text(html: str, max_chars: int = 12000) -> str:
    """HTML → 可读纯文本。优先 bs4，缺失时退化为正则剥标签。"""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "header", "footer",
                         "nav", "aside", "form", "iframe", "svg"]):
            tag.decompose()
        text = soup.get_text("\n")
    except ImportError:
        text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
        text = re.sub(r"(?s)<[^>]+>", "\n", text)
        import html as html_mod
        text = html_mod.unescape(text)
    lines = [ln.strip() for ln in text.splitlines()]
    text = "\n".join(ln for ln in lines if ln)
    return text[:max_chars]


# ==================== 搜索源 ====================

async def _search_bing(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    r = await client.get("https://cn.bing.com/search",
                         params={"q": query, "count": limit})
    r.raise_for_status()
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for li in soup.select("li.b_algo"):
        a = li.select_one("h2 a")
        if not a or not a.get("href", "").startswith("http"):
            continue
        snippet = li.select_one("p")
        out.append({"title": a.get_text(" ", strip=True), "url": a["href"],
                    "snippet": snippet.get_text(" ", strip=True) if snippet else ""})
        if len(out) >= limit:
            break
    return out


async def _search_duckduckgo(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    r = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
    r.raise_for_status()
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for res in soup.select("div.result"):
        a = res.select_one("a.result__a")
        if not a:
            continue
        href = a.get("href", "")
        # DDG 的跳转链接形如 //duckduckgo.com/l/?uddg=<真实URL>
        if "uddg=" in href:
            qs = parse_qs(urlparse(href).query)
            href = unquote(qs.get("uddg", [""])[0])
        if not href.startswith("http"):
            continue
        snippet = res.select_one(".result__snippet")
        out.append({"title": a.get_text(" ", strip=True), "url": href,
                    "snippet": snippet.get_text(" ", strip=True) if snippet else ""})
        if len(out) >= limit:
            break
    return out


async def _search_searxng(client: httpx.AsyncClient, base_url: str,
                          query: str, limit: int) -> list[dict]:
    if not base_url:
        raise ValueError("settings.searxng_url 未配置")
    r = await client.get(base_url.rstrip("/") + "/search",
                         params={"q": query, "format": "json"})
    r.raise_for_status()
    return [{"title": it.get("title", ""), "url": it.get("url", ""),
             "snippet": it.get("content", "")}
            for it in r.json().get("results", [])[:limit]]


async def search_web(client: httpx.AsyncClient, query: str,
                     settings: dict, log=print) -> list[dict]:
    """按 settings.search_provider 搜索，auto 模式逐源降级。"""
    provider = settings.get("search_provider", "auto")
    limit = settings.get("search_max_results", 6)
    order = {"auto": ["bing", "duckduckgo"],
             "bing": ["bing"], "duckduckgo": ["duckduckgo"],
             "searxng": ["searxng"]}.get(provider, ["bing", "duckduckgo"])
    for name in order:
        try:
            if name == "bing":
                results = await _search_bing(client, query, limit)
            elif name == "duckduckgo":
                results = await _search_duckduckgo(client, query, limit)
            else:
                results = await _search_searxng(
                    client, settings.get("searxng_url", ""), query, limit)
            if results:
                log(f"  [搜索] {name}: 「{query}」→ {len(results)} 条结果")
                return results
            log(f"  [搜索] {name}: 无结果，尝试下一个源")
        except Exception as e:
            log(f"  [搜索] {name} 失败: {type(e).__name__}: {str(e)[:80]}")
    return []


# ==================== 抓取与提炼 ====================

async def fetch_page(client: httpx.AsyncClient, url: str,
                     settings: dict, log=print) -> str:
    timeout = settings.get("research_timeout", 20)
    max_chars = settings.get("research_max_chars_per_page", 12000)
    try:
        r = await client.get(url, timeout=timeout)
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if "html" not in ctype and "text" not in ctype:
            log(f"  [抓取] 跳过非文本内容 ({ctype.split(';')[0]}): {url}")
            return ""
        text = extract_text(r.text, max_chars)
        log(f"  [抓取] {len(text)} 字符 ← {url}")
        return text
    except Exception as e:
        log(f"  [抓取] 失败 {url}: {type(e).__name__}: {str(e)[:80]}")
        return ""


async def digest_page(llm_client: httpx.AsyncClient, query: str, url: str,
                      page_text: str, settings: dict, log=print) -> str:
    """用本地模型把网页正文提炼为与检索词相关的要点笔记；失败返回原文截断。"""
    prompt = (
        f"下面是网页 {url} 的正文。请围绕主题「{query}」提炼要点笔记：\n"
        "- 只保留与主题相关的事实、数据、结论、代码/命令，无关内容丢弃\n"
        "- 用简洁的 Markdown 要点列表输出，保留原文中的关键术语\n"
        "- 若网页与主题基本无关，只输出一行：（无相关内容）\n\n"
        f"网页正文：\n{page_text}"
    )
    payload = base_payload(settings, prompt)
    content = await call_llm(llm_client, payload, settings, log=log)
    if content and "（无相关内容）" not in content[:20]:
        return content.strip()
    if content:
        return ""
    log("  [提炼] 模型不可用，保留原文截断")
    return page_text[: settings.get("research_max_chars_per_page", 12000) // 3]


async def aggregate_notes(llm_client: httpx.AsyncClient, query_label: str,
                          notes: list[str], settings: dict, log=print) -> str:
    """把多个来源要点去重合并为可直接作为章节参考的摘要。"""
    if not notes:
        return ""
    prompt = (
        f"以下是围绕「{query_label}」收集的多份网页要点。请合并为一份可靠的 Markdown 参考摘要：\n"
        "- 合并重复事实，保留彼此补充的细节、数据、术语和不同观点\n"
        "- 对存在冲突、无来源或时效敏感的信息标注“待核对”，不要自行编造或裁决\n"
        "- 按主题分组，保持精炼，最后给出“来源线索”列出对应 URL\n"
        "- 只输出摘要正文，不要解释处理过程\n\n"
        + "\n\n---\n\n".join(notes)
    )
    content = await call_llm(llm_client, base_payload(settings, prompt), settings, log=log)
    return content.strip() if content else ""


async def generate_queries(llm_client: httpx.AsyncClient, chapter_name: str,
                           chapter_prompt: str, settings: dict,
                           n: int = 3, log=print) -> list[str]:
    """由章节提示词自动生成搜索检索词（“自己学会去搜索”的入口）。"""
    prompt = (
        f"我要写一篇文档中的章节「{chapter_name}」，写作要求如下：\n{chapter_prompt}\n\n"
        f"请给出 {n} 条用于搜索引擎的中文或英文检索词，帮助我收集写作素材。\n"
        "要求：每行一条，只输出检索词本身，不要编号、引号或解释。"
    )
    payload = base_payload(settings, prompt)
    content = await call_llm(llm_client, payload, settings, log=log)
    if not content:
        return []
    queries = [ln.strip().strip("-•* ") for ln in content.splitlines() if ln.strip()]
    queries = [q for q in queries if 2 <= len(q) <= 80][:n]
    log(f"  [检索词] 模型生成 {len(queries)} 条: {' | '.join(queries)}")
    return queries


# ==================== 主流程 ====================

async def run_research(paths: TaskPaths, queries: list[str] | None = None,
                       chapter_index: int | None = None, name: str = "",
                       digest: bool | None = None, log=print) -> Path | None:
    """检索 → 抓取 → 提炼 → 写入 data/processed/web_<name>.txt。

    queries 为空且给了 chapter_index 时，先用模型从该章提示词生成检索词。
    返回生成的参考文件路径；完全失败返回 None。
    """
    settings = load_settings(paths)
    fetch_n = settings.get("research_fetch_pages", 3)
    if digest is None:
        digest = settings.get("research_digest", True)

    async with httpx.AsyncClient(headers=UA_HEADERS, follow_redirects=True,
                                 timeout=settings.get("research_timeout", 20)) as web, \
               httpx.AsyncClient() as llm_client:

        if not queries and chapter_index is not None:
            from .config import load_prompts
            prompts = load_prompts(paths)
            if chapter_index < 0 or chapter_index >= len(prompts):
                log(f"[错误] 章节编号超出范围（共 {len(prompts)} 章）")
                return None
            p = prompts[chapter_index]
            log(f"[检索] 为第 {chapter_index + 1} 章「{p['chapter']}」自动生成检索词 ...")
            queries = await generate_queries(
                llm_client, p["chapter"], p["prompt"], settings, log=log)
            if not queries:
                log("[错误] 检索词生成失败（模型不可用？可改用手动检索词）")
                return None
            if not name:
                name = f"ch{chapter_index + 1}_{slugify(p['chapter'], 24)}"
        if not queries:
            log("[错误] 没有检索词")
            return None
        if not name:
            name = slugify(queries[0])

        sections = []
        aggregate_inputs = []
        seen_urls = set()
        for query in queries:
            results = await search_web(web, query, settings, log=log)
            if not results:
                log(f"  [跳过] 「{query}」所有搜索源均无结果")
                continue
            listing = "\n".join(
                f"- [{r['title']}]({r['url']})\n  {r['snippet']}" for r in results)
            body_parts = []
            fetched = 0
            for r in results:
                if fetched >= fetch_n:
                    break
                if r["url"] in seen_urls:
                    continue
                seen_urls.add(r["url"])
                text = await fetch_page(web, r["url"], settings, log=log)
                if not text:
                    continue
                fetched += 1
                if digest:
                    log(f"  [提炼] {r['url']} ...")
                    note = await digest_page(llm_client, query, r["url"],
                                             text, settings, log=log)
                else:
                    note = text
                if note:
                    source_note = f"#### 来源: {r['title']}\n{r['url']}\n\n{note}"
                    body_parts.append(source_note)
                    aggregate_inputs.append(source_note)
            sections.append(
                f"## 检索词: {query}\n\n### 搜索结果列表\n{listing}\n\n"
                + ("\n\n".join(body_parts) if body_parts else "（未抓到可用正文）"))

        if not sections:
            log("[失败] 没有获得任何检索内容")
            return None

        out_path = paths.processed_dir / f"web_{slugify(name)}.txt"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        header = (f"# 联网检索资料汇编\n\n"
                  f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                  f"- 检索词: {'; '.join(queries)}\n"
                  f"- 提炼模式: {'本地模型要点笔记' if digest else '原文截断'}\n"
                  "- 注意: 内容来自互联网，仅作参考素材，事实性信息建议核对来源\n")
        atomic_write_text(out_path, header + "\n\n" + "\n\n---\n\n".join(sections) + "\n")
        log(f"[完成] 检索资料已保存: {out_path}")

        if settings.get("research_aggregate", True) and len(aggregate_inputs) > 1:
            log("[聚合] 正在去重合并多来源要点 ...")
            summary = await aggregate_notes(
                llm_client, "；".join(queries), aggregate_inputs, settings, log=log)
            if summary:
                summary_path = paths.processed_dir / f"web_{slugify(name)}_summary.txt"
                summary_header = (
                    "# 联网检索聚合摘要\n\n"
                    f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                    f"- 检索词: {'; '.join(queries)}\n"
                    f"- 来源要点数: {len(aggregate_inputs)}\n"
                    "- 注意: 本文件由模型跨来源去重整理，关键事实请回查原始汇编。\n\n"
                )
                atomic_write_text(summary_path, summary_header + summary + "\n")
                log(f"[完成] 聚合摘要已保存: {summary_path}")

        log(f"提示: 把 \"{out_path.name}\" 加入相关章节的 ref_files 即可作为参考资料使用。")
        return out_path
