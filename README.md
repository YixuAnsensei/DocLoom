# DocLoom — 本地大模型长文档自动化工作台

> 用一台跑得动 30B 级本地模型的电脑，稳定产出几万字的结构化长文档：
> 实验报告、论文精读笔记、Marp/Slidev 幻灯片……任何"分章节 + 参考资料"型写作任务。

DocLoom 把长文档任务拆成**逐章独立的无状态请求**发给本地 LLM（llama.cpp-server、
Ollama 等 OpenAI 兼容 API），每章带上自己的参考资料，逐章落盘、断点续跑——
从根上绕开小上下文窗口和上下文压缩失真的问题。

**引擎与任务彻底分离**：引擎只有一份代码；每个任务只是一个目录
（`settings.json` + `prompts.json` + 参考资料）。换任务 = 换目录，换类型 = 换模板。

[English README](README_en.md)

---

## ⚡ 快速跑通（5 步，3 分钟）

```bash
# 0) 装一次（已装可跳过）
pip install -e .

# 1) 从最实用的内置模板建一个任务（也成当前任务）
docloom new demo --template report

# 2) 启动本地 LLM 服务（任何 OpenAI 兼容 API 即可，如 llama.cpp-server）
#    然后打开 workspace/demo/config/settings.json 把 model / api_url 改成你的

# 3) 生成前预览：每章 token 预算 + 缺失文件检查
docloom review

# 4) 开跑（断点续传，随时 Ctrl+C，下次自动跳过已完成章节）
docloom run

# 5) 看产物
docloom status              # 每章状态
# workspace/demo/output/<最终文档>.md  ← 就是结果
```

后面想看怎么编辑章节、补充参考资料、改模板、用 Web UI——见下面"五分钟上手"与"目录结构"。

---

## 功能一览

- **逐章生成 + 状态链**：可选把前 N 章成稿注入当前章请求，保证前后文连贯
- **精确 token 预算**：自动调用 llama.cpp `/tokenize` 精确计数，失败自动回退启发式估算
- **四种截断策略**：head / tail / middle / smart，超预算时迭代收缩并用真实计数验证
- **图片两条路**：视觉模型直接看图（base64 多模态请求）；纯文本模型则先
  `docloom caption` 用视觉模型给图片生成文字描述，生成时注入描述
- **联网检索（web research）**：`docloom research` 自动搜索（Bing/DuckDuckGo/SearXNG，
  无需任何 API key）→ 抓取网页正文 → 本地模型提炼要点，结果落盘为参考资料文件；
  还能让模型**根据章节提示词自己生成检索词**（`--chapter N`）
- **候选稿修改流**：`modify` 默认生成候选稿而非直接覆盖，`accept` / `reject` 决定去留，
  附 diff 预览；也支持 `--in-place` 与批量修改（`batch-modify`，可断点续传）
- **review 预览**：生成前先出一份完整预览（每章提示词、参考资料、token 预算、
  缺失文件检查），确认无误再开跑
- **Web UI**：`docloom serve` 一条命令启动网页界面，浏览器里改提示词、跑生成、
  看日志、处理候选稿
- **全部原子写入**：任何时刻断电/中断都不会写坏配置和报告文件

## 安装

需要 Python 3.10+。核心很轻（只有 `httpx` + `beautifulsoup4`），
PDF/DOCX 解析、抽图、Web UI 是**按需安装的可选依赖**：

```bash
pip install -e .            # 核心：逐章生成 / review / 联网检索 / 候选稿流
pip install -e ".[docs]"    # 追加 PDF/DOCX 解析与抽图（pymupdf + python-docx）
pip install -e ".[web]"     # 追加 Web UI（fastapi + uvicorn）
pip install -e ".[all]"     # 一次装齐全部可选功能
```

装完多一个全局 `docloom` 命令（等价于 `python -m docloom`）。
想一键装全也可以用 `pip install -r requirements.txt`（等价于 `[all]`）。
没装对应可选依赖时运行 `parse` / `extract-images` / `serve`，会提示缺哪个 extra、怎么装。

本地模型端：任何 OpenAI 兼容的 `/v1/chat/completions` 服务均可
（llama.cpp-server、Ollama、vLLM…）。用 llama.cpp-server 时自动启用 `/tokenize` 精确计数。

## 五分钟上手

```bash
cd DocLoom

# 1. 看看有哪些模板
python -m docloom templates

# 2. 从模板建一个任务（会创建 workspace/my_report/ 并设为当前任务）
python -m docloom new my_report --template report

# 3. 把 PDF/DOCX 参考资料丢进 workspace/my_report/data/raw/，然后解析
python -m docloom parse
python -m docloom extract-images        # 可选：从 PDF 抽图
python -m docloom caption               # 可选：纯文本模型需要先给图配文字描述

# 4. 编辑章节定义（每章的标题、提示词、参考文件）
#    workspace/my_report/config/prompts.json

# 5. 生成前预览：每章 token 预算、缺失文件检查
python -m docloom review

# 6. 开跑（逐章生成，随时 Ctrl+C，重跑自动跳过已完成章节）
python -m docloom run

# 7. 对某章不满意？生成候选稿对比后再决定
python -m docloom modify 3 -p "第二段补充与 XX 的对比，语言更精炼"
python -m docloom candidates
python -m docloom accept 3      # 或 reject 3
```

### Web UI

```bash
python -m docloom serve            # 默认 http://127.0.0.1:8600
python -m docloom serve --host 0.0.0.0 --port 8600   # 局域网访问
```

网页里可以：新建任务（选模板）、编辑每章提示词/参考资料、增删/排序章节、
解析资料（parse / 抽图 / caption）、单章重跑、全量生成、实时看运行日志、
提修改要求生成候选稿并对比接受/放弃、直接编辑 settings.json、刷新 review 预览。

## 联网检索（web research）

没有现成资料？让 DocLoom 自己去网上找（无需任何搜索 API key）：

```bash
# 手动给检索词（可多个）
python -m docloom research "OpenHarmony 分布式软总线" "softbus architecture"

# 或者让模型读第 3 章的提示词，自己想检索词、自己去搜（"自己学会搜索"）
python -m docloom research --chapter 3
```

流程：搜索（Bing → DuckDuckGo 自动降级，或自建 SearXNG）→ 抓取网页正文 →
本地模型把每页提炼成与主题相关的要点笔记 → 汇编写入
`data/processed/web_*.txt`。把这个文件名加进章节的 `ref_files`，
它就和其他参考资料完全一样地参与生成。Web UI 的"运行"页和章节详情页
（"为本章联网检索素材"按钮）也能直接触发。

## 目录结构

```
DocLoom/
├── docloom/            # 引擎（唯一一份代码）
├── templates/          # 任务模板（settings + prompts + description.md）
│   ├── report/         #   实验报告（11 章示例）
│   ├── paper_notes/    #   论文精读笔记
│   ├── marp_slides/    #   Marp 幻灯片模板填空
│   └── slidev_slides/  #   Slidev 幻灯片模板填空（双栏/动画/代码页）
└── workspace/          # 你的所有任务（默认被 .gitignore 忽略）
    └── <任务名>/
        ├── config/
        │   ├── settings.json        # 模型、API、上下文窗口、截断策略…
        │   ├── prompts.json         # 章节定义（标题/提示词/参考文件/配图提示）
        │   └── task_state.json      # 各章 pending/completed（断点续跑依据）
        ├── data/
        │   ├── raw/                 # 原始 PDF/DOCX
        │   ├── processed/           # parse 出的纯文本 + 状态链历史
        │   ├── extracted_images/    # extract-images 抽出的图片（按 PDF 分目录）
        │   └── image_captions.json  # caption 生成的图片描述
        └── output/
            ├── <最终文档>.md
            ├── review_preview.md
            └── candidates/          # 待处理候选稿
```

多任务切换：`docloom tasks` 列出全部，`docloom use <名>` 设默认，
或任何命令加 `--task <名>` 临时指定；`--workspace <目录>` 可整体换工作区。

## settings.json 关键项

| 键 | 说明 |
|---|---|
| `model` / `api_url` | 模型名与 OpenAI 兼容 API 地址 |
| `context_window_tokens` | 模型上下文窗口（tokens） |
| `max_input_ratio` | 输入占窗口比例，其余留给输出 |
| `max_output_tokens` | 单次回复上限，null 不限制（思考型模型建议偏大或 null） |
| `enable_thinking` | false=关闭思维链（llama.cpp+Qwen3 系），null=服务器默认 |
| `extra_payload` | 原样合并进每次请求的额外参数，如 `{"top_p": 0.9}` |
| `truncation_strategy` | `smart` / `head` / `tail` / `middle` |
| `truncation_keep_ratio` | 截断时保留比例 |
| `state_chain` / `state_chain_limit` | 是否注入前几章成稿及注入章数 |
| `vision_model` | true = 直接发图（多模态）；false = 注入 caption 文字描述 |
| `tokenizer` | `auto`（优先 /tokenize，失败回退估算）/ `api` / `heuristic` |
| `caption_model` / `caption_api_url` | caption 用的视觉模型（默认同主模型） |
| `modify_in_place` | modify 默认是否直接覆盖（默认 false，走候选稿） |
| `search_provider` | 联网检索源：`auto`（bing→duckduckgo 降级）/ `bing` / `duckduckgo` / `searxng` |
| `research_digest` | true = 抓取的网页先用本地模型提炼要点再落盘；false = 保留原文截断 |
| `research_fetch_pages` | 每条检索词实际抓取正文的网页数（默认 3） |
| `system_prompt` | 全文档统一的系统提示词（人设、格式要求） |

完整字段说明见 [doc/GUIDE.md](doc/GUIDE.md)。

## prompts.json 每章字段

```json
{
  "chapter": "章节标题（会成为报告里的 ## 标题，也是定位/替换的锚点）",
  "prompt": "本章的生成提示词",
  "ref_files": ["1.txt", "paper1/page_5_img_1.png"],
  "image_hints": ["OpenHarmony系统架构图"]
}
```

`ref_files` 支持 `data/processed` 下的文本与 `data/extracted_images` 下的图片
（含子目录写法）；`image_hints` 只是给你自己看的配图备忘（`docloom hints` 汇总）。

## 自定义模板 = 泛化到任何文档类型

把任何调好的任务一键导出为模板：

```bash
python -m docloom save-template 我的模板名 --desc "一句话描述"
```

（Web UI 的"设置"页也有"导出模板"按钮。）之后
`docloom new xxx --template 我的模板名` 即可无限复用。周报、小说章节、
课程讲义、翻译对照稿……任何"分章节 + 参考资料"的写作都能这样固化下来，
详见 [doc/GUIDE.md](doc/GUIDE.md) 的泛化教程。

## 命令速查

```
new <名> [--template T]   从模板新建任务        tasks / use <名>      任务列表/切换
save-template <名>        当前任务导出为模板     templates             模板列表
parse                     PDF/DOCX → 纯文本     extract-images        PDF 抽图
caption [--force]         图片→文字描述          review                生成前预览
run [N]                   生成全部/第 N 章       status                章节状态
reset N / reset-all       重置章节               hints                 配图建议清单
modify N -p "要求"        生成候选稿             candidates            候选稿列表
accept N / reject N       接受/放弃候选稿        batch-modify          批量修改(续传)
research "词" [--chapter N]  联网检索素材        serve [--port P]      启动 Web UI
```

## License

MIT
