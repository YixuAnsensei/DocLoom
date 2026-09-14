"""配置与任务目录管理。

一个"任务"是 workspace/ 下的一个目录，内部结构与旧版三个独立项目一致：
  <task>/config/settings.json   全局设置
  <task>/config/prompts.json    章节定义
  <task>/config/task_state.json 进度状态
  <task>/data/raw               原始 PDF/DOCX
  <task>/data/processed         解析后的 txt / 状态链缓存
  <task>/data/extracted_images  从 PDF 提取的图片
  <task>/output                 生成结果 / 候选稿 / 预览
"""

from dataclasses import dataclass
from pathlib import Path

from .utils import load_json, save_json

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}

DEFAULT_SETTINGS = {
    "project_name": "未命名项目",
    "model": "Qwen3.6",
    "api_url": "http://localhost:11434/v1/chat/completions",
    "temperature": 0.3,
    "request_timeout": 600,
    "max_retries": 3,
    "max_output_tokens": None,
    "enable_thinking": None,
    "_thinking_comment": "思考型模型开关：false=关闭思维链（llama.cpp+Qwen3 系有效），true=强制开启，null=服务器默认。",
    "extra_payload": {},
    "_extra_payload_comment": "原样合并进每次请求体的额外参数，如 {\"top_p\": 0.9} 或其他后端的专有字段。",
    "output_file": "output/Final_Report.md",
    "system_prompt": "你是一个专业的技术文档撰写者。严格输出 Markdown 正文，不要包含分析过程和寒暄。",
    # ========== 上下文窗口管理 ==========
    "context_window_tokens": 56000,
    "max_input_ratio": 0.75,
    "truncation_strategy": "smart",
    "truncation_keep_ratio": 0.6,
    # ========== token 计数 ==========
    "tokenizer": "auto",
    "_tokenizer_comment": "auto=优先调用 llama.cpp 的 /tokenize 接口精确计数，失败回退启发式估算；api=强制接口；heuristic=强制估算。",
    "tokenizer_api_url": "",
    "_tokenizer_api_comment": "留空则根据 api_url 自动推导（同主机 /tokenize）。",
    # ========== 多模态视觉模型 ==========
    "vision_model": False,
    "_vision_comment": "true=模型支持图像输入，ref_files 中的图片会编码为 base64 直接发给模型。",
    "vision_image_tokens": 512,
    # ========== 图片描述（caption）流程 ==========
    "caption_model": "",
    "caption_api_url": "",
    "_caption_comment": "运行 `docloom caption` 时使用的视觉模型与 API，留空则复用主模型配置。生成的描述存于 data/image_captions.json，纯文本模型也能借此\"看图\"。",
    "caption_prompt": "请用中文简要描述这张图片的内容与要点（150 字以内），如果是图表请说明其坐标轴、趋势与结论。只输出描述本身。",
    # ========== 前序章节状态链 ==========
    "state_chain": False,
    "state_chain_limit": 1,
    "_state_chain_comment": "true=生成后续章节时自动把前 N 章生成结果加入参考资料，保持连贯。",
    # ========== 修改流程 ==========
    "modify_in_place": False,
    "_modify_comment": "false=修改结果先存为候选稿（output/candidates/），用 accept/reject 决定是否替换；true=旧行为，直接原地替换。",
    "report_history_keep": 10,
    "_report_history_comment": "每次替换已有章节前保留的报告版本快照数量；0=不保留。",
    # ========== 联网检索（web research） ==========
    "search_provider": "auto",
    "_search_comment": "auto=依次尝试 bing→duckduckgo；也可指定 bing / duckduckgo / searxng。全部无需 API key。",
    "searxng_url": "",
    "_searxng_comment": "search_provider=searxng 时的实例地址，如 http://localhost:8080。",
    "search_max_results": 6,
    "research_fetch_pages": 3,
    "_research_fetch_comment": "每条检索词实际抓取正文的网页数（搜索结果列表全部保留，正文只抓前几个）。",
    "research_digest": True,
    "_research_digest_comment": "true=抓到的网页正文先用本地模型提炼成要点笔记再落盘；false=保留原文截断。",
    "research_aggregate": True,
    "_research_aggregate_comment": "多条检索词时，额外输出一份跨来源去重的 summary 文件。",
    "research_timeout": 20,
    "research_max_chars_per_page": 12000,
}

DEFAULT_PROMPTS = [
    {
        "chapter": "第1章 示例章节",
        "prompt": "请撰写关于该主题的详细内容。如需自定义，请编辑 config/prompts.json 文件。",
        "ref_files": [],
        "image_hints": [],
    },
]


@dataclass
class TaskPaths:
    """一个任务内所有关键路径的集合。"""

    root: Path

    @property
    def name(self) -> str:
        return self.root.name

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def settings_path(self) -> Path:
        return self.config_dir / "settings.json"

    @property
    def prompts_path(self) -> Path:
        return self.config_dir / "prompts.json"

    @property
    def state_path(self) -> Path:
        return self.config_dir / "task_state.json"

    @property
    def modifications_path(self) -> Path:
        return self.config_dir / "modifications.json"

    @property
    def modification_state_path(self) -> Path:
        return self.config_dir / "modification_state.json"

    @property
    def raw_dir(self) -> Path:
        return self.root / "data" / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.root / "data" / "processed"

    @property
    def images_dir(self) -> Path:
        return self.root / "data" / "extracted_images"

    @property
    def captions_path(self) -> Path:
        return self.root / "data" / "image_captions.json"

    @property
    def candidates_dir(self) -> Path:
        return self.root / "output" / "candidates"

    @property
    def review_path(self) -> Path:
        return self.root / "output" / "review_preview.md"

    def output_path(self, settings: dict) -> Path:
        return self.root / settings.get("output_file", "output/Final_Report.md")

    def ensure_dirs(self) -> None:
        for d in (self.config_dir, self.raw_dir, self.processed_dir,
                  self.root / "output"):
            d.mkdir(parents=True, exist_ok=True)


# 老配置字段别名 → 新字段名（集中登记，兼容历史 settings.json）
_LEGACY_SETTING_ALIASES = {
    "state_chain_depth": "state_chain_limit",
}


def migrate_legacy_keys(user: dict) -> dict:
    """把历史字段名迁移到当前字段名（仅在新字段缺失时补写）。"""
    for old, new in _LEGACY_SETTING_ALIASES.items():
        if old in user and new not in user:
            user[new] = user[old]
    return user


def load_settings(paths: TaskPaths) -> dict:
    """加载设置，缺失字段用默认值补齐（老配置文件自动兼容新功能）。"""
    user = migrate_legacy_keys(load_json(paths.settings_path, DEFAULT_SETTINGS))
    settings = dict(DEFAULT_SETTINGS)
    settings.update(user)
    return settings


def load_prompts(paths: TaskPaths) -> list:
    """加载章节提示词，向后兼容旧 ref_file (string) 格式。"""
    prompts = load_json(paths.prompts_path, DEFAULT_PROMPTS)
    for p in prompts:
        p.setdefault("image_hints", [])
        if "ref_file" in p and "ref_files" not in p:
            raw = p.pop("ref_file")
            p["ref_files"] = [raw] if raw else []
        p.setdefault("ref_files", [])
    return prompts


def load_task_state(paths: TaskPaths, chapter_count: int) -> dict:
    default_state = {str(i): "pending" for i in range(chapter_count)}
    state = load_json(paths.state_path, default_state)
    for i in range(chapter_count):
        state.setdefault(str(i), "pending")
    return state


def save_task_state(paths: TaskPaths, state: dict) -> None:
    save_json(paths.state_path, state)


# ==================== workspace 任务发现 ====================

def find_workspace_root(start: Path | None = None) -> Path:
    """定位 workspace/ 目录。显式传入 start（如 --workspace）时以其为准：
    start 本身叫 workspace 则直接使用，否则使用 start/workspace（不要求已存在）。
    未显式指定时，从 cwd 向上找含 workspace/ 的目录。"""
    if start is not None:
        cur = start.resolve()
        return cur if cur.name == "workspace" else cur / "workspace"
    cur = Path.cwd().resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / "workspace").is_dir():
            return candidate / "workspace"
        if candidate.name == "workspace" and candidate.is_dir():
            return candidate
    # 兜底：包安装目录的同级 workspace（源码运行场景）
    pkg_root = Path(__file__).resolve().parent.parent
    return pkg_root / "workspace"


def list_tasks(ws_root: Path) -> list[TaskPaths]:
    if not ws_root.exists():
        return []
    tasks = []
    for d in sorted(ws_root.iterdir()):
        if d.is_dir() and (d / "config" / "settings.json").exists():
            tasks.append(TaskPaths(d))
    return tasks


def resolve_task(ws_root: Path, name: str | None) -> TaskPaths:
    """按 --task 参数 / .current 记录 / 唯一任务 的顺序确定当前任务。"""
    if name:
        root = ws_root / name
        if not (root / "config").exists():
            raise SystemExit(f"[错误] 任务不存在: {name}（workspace: {ws_root}）")
        return TaskPaths(root)

    current_file = ws_root / ".current"
    if current_file.exists():
        recorded = current_file.read_text(encoding="utf-8").strip()
        root = ws_root / recorded
        if (root / "config").exists():
            return TaskPaths(root)

    tasks = list_tasks(ws_root)
    if len(tasks) == 1:
        return tasks[0]
    if not tasks:
        raise SystemExit(
            f"[错误] workspace 中没有任务（{ws_root}）。\n"
            "先创建一个: docloom new 我的任务 --template report"
        )
    names = ", ".join(t.name for t in tasks)
    raise SystemExit(
        f"[错误] workspace 中有多个任务（{names}），请用 --task 指定，"
        "或运行 `docloom use <任务名>` 设为默认。"
    )


def set_current_task(ws_root: Path, name: str) -> None:
    (ws_root / ".current").write_text(name, encoding="utf-8")


def templates_root() -> Path:
    return Path(__file__).resolve().parent.parent / "templates"


def export_template(paths: TaskPaths, tpl_name: str,
                    description: str = "", force: bool = False) -> Path:
    """把任务的 settings + prompts 导出为可复用模板（泛化到新任务类型的入口）。

    已存在同名模板且未指定 force 时抛 FileExistsError。
    """
    target = templates_root() / tpl_name
    if target.exists() and not force:
        raise FileExistsError(str(target))
    target.mkdir(parents=True, exist_ok=True)
    save_json(target / "settings.json", load_settings(paths))
    save_json(target / "prompts.json", load_prompts(paths))
    desc = description.strip() or f"由任务「{paths.name}」导出的模板"
    (target / "description.md").write_text(desc + "\n", encoding="utf-8")
    return target
