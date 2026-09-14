# DocLoom 详细使用指南

> 这份指南假设你完全没接触过 DocLoom。读完你会知道：它的每个概念是什么、
> 网页界面每个按钮干什么、每条命令每个配置项什么意思、
> 以及最重要的——**怎么把它泛化到你想做的任何新文档类型**。

---

## 目录

1. [三个核心概念](#1-三个核心概念)
2. [第一次启动](#2-第一次启动)
3. [Web 界面逐页详解（推荐日常用法）](#3-web-界面逐页详解)
4. [一个任务的完整生命周期](#4-一个任务的完整生命周期)
5. [泛化教程：把 DocLoom 用到任何新项目上](#5-泛化教程把-docloom-用到任何新项目上)
6. [settings.json 全字段说明](#6-settingsjson-全字段说明)
7. [prompts.json 章节定义说明](#7-promptsjson-章节定义说明)
8. [CLI 命令完整参考](#8-cli-命令完整参考)
9. [图片的两种用法](#9-图片的两种用法)
10. [常见问题排查](#10-常见问题排查)
11. [联网检索：让它自己去网上找资料](#11-联网检索让它自己去网上找资料)

---

## 1. 三个核心概念

DocLoom 里只有三个东西，理解了它们就理解了一切：

**引擎（`docloom/` 目录）**
唯一的一份代码。负责：把长文档拆成逐章请求、管理上下文窗口和截断、
调用你的本地模型、把结果原子写入报告文件、断点续跑。你永远不需要改它。

**任务（`workspace/<任务名>/` 目录）**
一次具体的写作工作，比如"这学期的实验报告"。一个任务 = 一个目录：

```
workspace/我的任务/
├── config/
│   ├── settings.json      ← 用什么模型、多大窗口、什么人设
│   ├── prompts.json       ← 文档分几章、每章写什么、参考什么资料
│   └── task_state.json    ← 每章 pending/completed（断点续跑的依据，程序自己维护）
├── data/
│   ├── raw/               ← 你丢原始 PDF/DOCX 的地方
│   ├── processed/         ← `parse` 转出的纯文本（参考资料从这里读）
│   ├── extracted_images/  ← `extract-images` 抽出的图片（按 PDF 分子目录）
│   └── image_captions.json ← `caption` 生成的图片文字描述
└── output/
    ├── <最终文档>.md       ← 成果
    ├── review_preview.md  ← 生成前的预览检查单
    └── candidates/        ← 修改产生的候选稿（等你接受/放弃）
```

**模板（`templates/<模板名>/` 目录）**
一个任务"抽掉数据后剩下的配置"——只有 settings.json + prompts.json +
一行描述。`docloom new 任务 --template 模板` 就是把模板复制成新任务的 config。
**任务 ↔ 模板可以双向转换**：调好的任务随时 `save-template` 固化成模板。
这就是 DocLoom 泛化能力的来源：新文档类型 = 新模板，引擎代码零改动。

任务之间怎么切换：`docloom use <名>` 设默认（记在 `workspace/.current`），
或任何命令临时加 `--task <名>`。整个 workspace 也能换：`--workspace <目录>`。

---

## 2. 第一次启动

```bash
# 依赖（你的机器已装好，新机器才需要）
pip install -r requirements.txt

# 你的电脑上用 Anaconda 的 Python（MSYS2 的装不了 PyMuPDF）：
cd "C:/Users/user'name/Desktop/DocLoom"
"D:/Anaconda/python.exe" -m docloom serve
```

浏览器打开 **http://127.0.0.1:8600** 即可。模型端保持你现有习惯：
llama.cpp-server 挂在 `localhost:11434`，settings 里就是这个地址。

想让局域网里其他人用你的部署：

```bash
"D:/Anaconda/python.exe" -m docloom serve --host 0.0.0.0 --port 8600
# 其他人访问 http://<你的局域网IP>:8600
```

> ⚠️ Web 界面**没有任何登录/鉴权**：开放到 0.0.0.0 后，局域网里任何人都能
> 改你的配置、启动生成、读输出。只在可信网络里这么做，公网上千万不要。

---

## 3. Web 界面逐页详解

界面 = 左侧任务栏 + 顶部五个页签。

### 左侧任务栏

- 列出 workspace 里所有任务，显示项目名和"已完成章数/总章数"；
  正在后台生成的任务会挂 **运行中** 标记（每 8 秒自动刷新）。
- 点任务名切换当前任务，所有页签内容随之刷新。
- **＋ 新建任务**：弹窗里填任务名（用英文或拼音，会成为目录名）、
  选一个模板（或"空白任务"），点创建。创建即设为当前任务。

### 页签 1：章节

任务的主工作区，两层结构：

**章节列表**：每章一行，✅=已生成 ⬜=未生成，显示参考资料清单；
有待处理候选稿的章节会挂"候选稿待处理"黄色标记。点任意一章进入详情。
每行右侧有 **↑ ↓ ✕**：上移/下移/删除该章（会自动同步各章完成状态、
状态链缓存和候选稿的对应关系）；列表下方 **＋ 新增章节** 在末尾加一章。
删除只删章节定义，报告里已生成的正文不动；换序后成品里的顺序不变，
需要成品顺序也变时 reset-all 重跑。

**章节详情**（点进某一章后）：
- **章节提示词**：这一章的生成指令，直接在文本框里改。
- **参考资料**：逗号分隔的文件名（`data/processed` 下的 `.txt` 或
  `data/extracted_images` 下的图片，图片可写子目录如 `paper1/page_5_img_1.png`）。
- **保存提示词/参考**：只保存，不生成。
- **重新生成本章**：先自动保存你的修改，再后台重跑这一章（会覆盖本章现有内容），
  页面自动跳到"运行"页看日志。
- **为本章联网检索素材**：模型读本章提示词自动生成检索词并联网搜索，
  结果存为 `web_chN_*.txt`（详见 §11 联网检索），完成后把文件名填进参考资料即可。
- **对本章提出修改要求**：填一句自然语言要求（如"第二段补充与 XX 的对比"），
  点**生成候选稿**。模型基于本章现有内容改写，结果存为候选稿，**不动原文**。
- 下方左右两栏对照：左边**当前版本**，右边**候选稿**（有的话），
  候选稿上方有**接受**（替换进报告）和**放弃**两个按钮。

### 页签 2：运行

- **▶ 生成全部 pending 章节**：一键跑完所有未完成章节（已完成的自动跳过，
  所以中断后再点就是断点续跑）。
- **全部重置为 pending**：想整篇重写时用（不删除已有报告文件，重跑时逐章覆盖）。
- **资料处理三按钮**：解析 raw 资料（= `docloom parse`）、抽取 PDF 图片
  （= `extract-images`）、生成图片描述（= `caption`，需要模型在线）。
  都在后台跑，日志同样显示在下方。
- **🔍 联网检索**：填检索词（逗号分隔多条）直接发起检索，日志实时可见，
  详见 §11。
- 下方是实时日志（1.5 秒轮询）：每章的 token 用量、精确/估算计数来源、
  截断情况、重试、成功字符数都在这里。日志停在底部时自动跟随滚动。
- 同一任务同时只允许一个后台运行，重复点会提示 409。

### 页签 3：输出预览

当前任务最终 Markdown 文档的只读预览，顶部显示文件完整路径。
点"刷新"拿最新内容。要交付时直接去那个路径拿 `.md` 文件。

### 页签 4：设置

- 上半部分：**settings.json 的完整 JSON 编辑器**，改完点"保存设置"立即生效
  （JSON 格式错误会弹窗提示，不会写坏文件）。常改的就是模型名、API 地址、
  上下文窗口、`enable_thinking`、`state_chain`。
- 下半部分：**把当前任务存为模板**——填模板名（英文/拼音）、一句话描述，
  点"导出模板"。之后"新建任务"的模板下拉里立刻就能选到它。

### 页签 5：Review 预览

点"重新生成预览"，输出一份生成前检查单（和 `docloom review` 命令等价）：
每章的状态、参考资料是否缺失（缺失会标 ⚠️）、状态链注入了哪些前章、
**每章 token 预算明细**（系统+提示词+参考+图片 ≈ 总量 / 窗口占比）、提示词全文。
**大批量生成前先看一眼这里，能省掉整晚跑废的 GPU 时间。**

---

## 4. 一个任务的完整生命周期

以"写一份新实验报告"为例，全程可以只用网页（括号里是等价 CLI）：

1. **建任务**：新建任务 → 名字 `robot_report` → 模板选 `report`
   （`docloom new robot_report --template report`）
2. **放资料**：把讲义/手册 PDF 丢进 `workspace/robot_report/data/raw/`
3. **解析**：`docloom parse`（PDF/DOCX → processed/*.txt；网页运行页也有对应按钮）
   需要图就再 `docloom extract-images`；纯文本模型再 `docloom caption`
4. **定义章节**：章节页里逐章改提示词和参考文件；增删/排序章节也在章节页
   （或直接编辑 `config/prompts.json`）
5. **预检**：Review 预览页看 token 预算和缺失文件（`docloom review`）
6. **生成**：运行页 ▶（`docloom run`）。中断随时续跑。
7. **打磨**：对不满意的章节提修改要求 → 看 diff/候选稿 → 接受或放弃
   （`docloom modify N -p "..."` / `accept N` / `reject N`）
8. **交付**：输出预览页拿最终 `.md`
9. **固化**：如果这套配置调得好，设置页"导出模板"，下学期直接复用
   （`docloom save-template report_v2`）

---

## 5. 泛化教程：把 DocLoom 用到任何新项目上

**DocLoom 不是"三个项目的合并"，而是一个通用模式的引擎。**
这个模式是：*任何能拆成「N 个部分 × 每部分（指令 + 参考资料）」的长文本工作*。
判断一个新想法能不能用 DocLoom：能列出章节清单，就能用。

### 通用方法论（四步）

1. **拆结构** → 决定 prompts.json：文档分哪几部分？每部分标题叫什么？
2. **定人设** → 决定 system_prompt：作者是谁、什么口吻、什么格式纪律
   （格式纪律写在 system_prompt，比写在每章 prompt 里省 token 且更稳定）
3. **配参数** → 决定 settings：需要前后连贯吗（state_chain）？
   要创造性还是要忠实（temperature）？参考资料很长吗（截断策略）？
4. **跑通一章 → 固化** → 先 `run 1` 试一章，调到满意后 `save-template`

### 实例 A：每周工作周报

```
system_prompt: "你是一名软件工程师，用简洁的要点式中文写周报，每节不超过 200 字。"
章节: 本周完成 / 遇到的问题 / 下周计划
ref_files: 把本周的 git log、会议记录导出成 txt 丢进 raw
state_chain: false（三节互相独立）    temperature: 0.3
```

### 实例 B：长篇小说 / 连载

```
system_prompt: 世界观 + 文风约定（"第三人称过去式，禁止上帝视角"）
章节: 第一章…第 N 章，每章 prompt 写剧情大纲
ref_files: 人物设定.txt、世界观.txt（每章都挂）
state_chain: true, state_chain_limit: 2~3（剧情连贯的命脉）
temperature: 0.7~0.9（要创造性）      truncation_strategy: tail（最近剧情最重要）
```

### 实例 C：课程讲义 / 教程系列

```
system_prompt: "面向零基础读者的讲师，每章含引入、正文、示例代码、小结、3 道练习。"
章节: 按教学大纲一章一课
ref_files: 官方文档导出的 txt、上一版讲义
state_chain: true, state_chain_limit: 1（衔接上一课的"上回说到"）
```

### 实例 D：文档翻译 / 双语对照

```
system_prompt: "专业译者。输出格式：每段先原文引用块，后中文译文。禁止增删信息。"
章节: 按原文档的章节切分，每章 ref_files 挂对应章节的原文 txt
prompt: "翻译参考资料中的全部内容"
temperature: 0.1~0.2    state_chain: false    tokenizer: auto（术语表可另挂一个 txt）
```

### 实例 E：文献综述

```
章节: 引言 / 主题一综述 / 主题二综述 / 对比分析 / 结论
每章 ref_files 挂对应的几篇论文（parse 后的 txt）
对比分析章开 state_chain 引用前面各章成稿
truncation_strategy: smart（论文长，头尾都要）
```

### 经验法则

- **一章的产出控制在 1000–3000 字**。太长的章拆成小节，小模型在短任务上远更稳。
- **参考资料宁可多个小 txt，别一个巨型 txt**——截断以整个 ref 拼接体为单位，
  小文件让"每章只挂相关资料"成为可能，这是控制质量的第一杠杆。
- **格式要求全部进 system_prompt**，每章 prompt 只写内容差异。
- **模板迭代**：v1 跑完整任务 → 把发现的问题改进 prompt → `save-template xxx_v2 --force`。
  模板就是你的提示词工程资产库。

---

## 6. settings.json 全字段说明

| 字段 | 默认 | 说明 |
|---|---|---|
| `project_name` | 未命名项目 | 显示用的项目名（报告标题不受它影响） |
| `model` | Qwen3.6 | 发给 API 的模型名 |
| `api_url` | http://localhost:11434/v1/chat/completions | OpenAI 兼容接口完整地址 |
| `temperature` | 0.3 | 越低越忠实（模板填空 0.1–0.2），越高越有创造性（小说 0.7+） |
| `request_timeout` | 600 | 单次请求超时秒数；`null` = 不限时（大模型慢机器建议 null） |
| `max_retries` | 3 | 失败重试次数（指数退避 2,4,8…最长 60 秒） |
| `max_output_tokens` | null | 单章回复上限；null 不限制。**思考型模型别设太小**（见排查 §10） |
| `enable_thinking` | null | `false` 关闭思维链（llama.cpp+Qwen3 系有效）；`true` 强制开；null 随服务器 |
| `extra_payload` | {} | 原样并入每次请求体，如 `{"top_p":0.9,"repeat_penalty":1.05}`；也可放其他后端的思考开关 |
| `output_file` | output/Final_Report.md | 最终文档相对任务目录的路径 |
| `system_prompt` | （通用写作者） | 全文档统一人设与格式纪律，**泛化时最重要的字段** |
| `context_window_tokens` | 56000 | 模型实际加载的上下文长度，要和 llama.cpp 的 `-c` 一致 |
| `max_input_ratio` | 0.75 | 输入最多占窗口的比例，剩下留给输出 |
| `truncation_strategy` | smart | 参考超预算时怎么裁：`head` 留头 / `tail` 留尾 / `middle` 留中 / `smart` 大头+小尾 |
| `truncation_keep_ratio` | 0.6 | 裁剪保留比例（配合迭代收缩，用真实计数验证不超标） |
| `tokenizer` | auto | `auto` 优先 /tokenize 精确计数、失败自动回退估算；`api` 强制接口；`heuristic` 强制估算 |
| `tokenizer_api_url` | "" | 留空自动从 api_url 推导同主机的 `/tokenize` |
| `vision_model` | false | true=模型能看图，图片 base64 直接进请求；false=用 caption 文字描述代替 |
| `vision_image_tokens` | 512 | 预算里每张图按多少 token 估 |
| `caption_model` / `caption_api_url` | "" | `docloom caption` 用的视觉模型，留空复用主模型 |
| `caption_prompt` | （中文描述指令） | 给图片生成描述时的提示词 |
| `state_chain` | false | true=生成第 N 章时自动注入前几章成稿作参考 |
| `state_chain_limit` | 1 | 注入最近几章（写作 `state_chain_depth` 也能识别） |
| `modify_in_place` | false | modify 默认走候选稿；true 恢复直接覆盖的旧行为 |
| `search_provider` | auto | 联网检索源：`auto`=bing→duckduckgo 依次尝试；或指定 `bing`/`duckduckgo`/`searxng`，全部免 API key |
| `searxng_url` | "" | search_provider=searxng 时的实例地址（如 http://localhost:8080） |
| `search_max_results` | 6 | 每条检索词保留的搜索结果条数 |
| `research_fetch_pages` | 3 | 每条检索词实际抓取正文的网页数（结果列表全保留，正文只抓前几个） |
| `research_digest` | true | 抓到的正文先用本地模型提炼要点再落盘；false=保留原文截断（模型没开时自动退化为此） |
| `research_timeout` | 20 | 单个网页请求超时秒数 |
| `research_max_chars_per_page` | 12000 | 每页正文最多保留的字符数 |

以 `_` 开头的键（如 `_thinking_comment`）只是写在配置里的注释，引擎会忽略。

## 7. prompts.json 章节定义说明

一个 JSON 数组，一个元素 = 一章，顺序即文档顺序：

```json
[
  {
    "chapter": "章节标题",
    "prompt": "这一章的生成指令，可以很长很具体",
    "ref_files": ["1.txt", "paper1/page_5_img_1.png"],
    "image_hints": ["此处建议放系统架构图"]
  }
]
```

- `chapter`：会成为报告里的 `## 标题`，也是这一章后续被定位/替换/修改的**锚点**，
  生成后尽量别改（改了引擎会尝试用" — "前的前缀模糊匹配，但不保证）。
- `prompt`：本章指令。内容要求写这里，格式要求写 system_prompt。
- `ref_files`：文本文件在 `data/processed/` 找，图片在 `data/extracted_images/`
  找（支持子目录），也兜底找 `data/`。缺失文件 review 会用 ⚠️ 标出。
- `image_hints`：不参与生成，纯粹给你自己的配图备忘（`docloom hints` 汇总打印）。

增删章节 / 调整章节顺序：网页章节页直接操作（会自动同步各章状态），
或编辑此文件。新增的章自动是 pending，下次 run 就会生成。

## 8. CLI 命令完整参考

所有命令支持 `--task/-t 任务名` 和 `--workspace/-w 目录`。

| 命令 | 说明 |
|---|---|
| `new <名> [--template T]` | 从模板建任务并设为当前任务 |
| `tasks` | 列出所有任务与进度 |
| `use <名>` | 切换当前默认任务 |
| `templates` | 列出可用模板 |
| `save-template <名> [--desc D] [--force]` | **当前任务导出为模板** |
| `parse` | data/raw 的 PDF/DOCX → data/processed 纯文本 |
| `extract-images [-f 文件] [--min-width W] [--min-height H]` | 从 PDF 抽图（默认过滤 <100px 小图） |
| `caption [--model M] [--api-url U] [--force]` | 视觉模型给图片生成文字描述（断点续传；--force 全部重来） |
| `review` | 生成 output/review_preview.md 预检单 |
| `run [N]` | 生成全部 pending 章节；带 N 只跑第 N 章（1 开始） |
| `status` | 各章状态一览 |
| `hints` | 汇总所有 image_hints 配图备忘 |
| `reset N [-p "新提示词"]` | 第 N 章重置为 pending（可顺便改提示词），并清掉它的状态链历史 |
| `reset-all` | 全部重置 + 清空状态链历史缓存 |
| `modify N -p "要求"` | 按要求改第 N 章 → 候选稿 + diff（`--in-place` 直接覆盖；`--ref` 临时换参考；`--dry-run` 只预览不请求） |
| `modify 1 3 -p "要求1" -p "要求3"` | 一次改多章（章号与 -p 一一对应） |
| `batch-modify [--dry-run] [--in-place]` | 从 config/modifications.json 批量修改，断点续传 |
| `reset-modifications` | 清批量修改进度 |
| `candidates` | 列出待处理候选稿 |
| `accept N` / `reject N` | 接受（替换进报告）/ 放弃候选稿 |
| `research "词1" ["词2"…] [--name X] [--no-digest]` | 联网检索素材 → data/processed/web_*.txt |
| `research --chapter N` | 让模型读第 N 章提示词**自动生成检索词**再去搜 |
| `serve [--host H] [--port P]` | 启动 Web UI（默认 127.0.0.1:8600） |

## 9. 图片的两种用法

**路线 1：模型本身能看图**（`vision_model: true`，如多模态 Qwen）
ref_files 里的图片被 base64 编码直接放进请求，模型"亲眼"看图写作。
每张图按 `vision_image_tokens` 计入预算。

**路线 2：纯文本模型**（`vision_model: false`）
先跑一次 `docloom caption`：用视觉模型（可以是另一个 API/模型，
`caption_model`/`caption_api_url` 指定）给 extracted_images 里的每张图生成
文字描述，存进 `data/image_captions.json`。之后生成时，ref_files 里的图片
自动替换为对应的文字描述注入。没跑 caption 就引用图片时，日志会提醒你。

典型工作流：`extract-images` → 打开目录删掉无用图 → `caption` →
在 prompts.json 里给相关章节挂上需要的图。

## 10. 常见问题排查

**生成结果是空的 / 日志说"空回复：输出额度耗尽"**
思考型模型（Qwen3 系）把 `max_output_tokens` 全烧在思维链上了。
三选一：把 `max_output_tokens` 调大或设 null；设 `"enable_thinking": false`；
或在 `extra_payload` 里放你的后端的思考开关。

**日志显示 token 计数是"估算(启发式)"而不是"精确(/tokenize)"**
llama.cpp-server 没开、或 `tokenizer_api_url` 推导不出来。不影响功能，
只是预算是 ±15% 的估算。服务器开着的话检查 api_url 是否同主机同端口。

**报告某一章定位不到（modify 说"现有内容: 未找到"）**
这一章的 `## 标题` 在报告里被手工改过/删过。把报告里的标题改回与
prompts.json 的 `chapter` 一致即可（或利用" — "前缀模糊匹配）。

**409：该任务已有后台运行在进行中**
同任务同时只允许一个生成。等跑完，或重启 serve 进程。

**PyMuPDF 装不上（你的 MSYS2 Python）**
MSYS2 的 mingw Python 没有官方 wheel。用 Anaconda 的
`D:\Anaconda\python.exe`（本指南所有命令都这么写）。

**换了模型 / 换了机器要改哪里？**
只改任务的 settings.json：`model`、`api_url`、`context_window_tokens`
（对齐新模型的 `-c`）。模板同理。引擎零改动。

**中断了怎么办？**
随时 Ctrl+C / 断电。task_state.json 与报告都为原子写入，再次 `run` 自动跳过
已完成章节继续。批量修改（batch-modify）同样断点续传。

---

## 11. 联网检索：让它自己去网上找资料

没有现成的 PDF/讲义时，DocLoom 可以自己去互联网收集素材。
**全程不需要任何搜索 API key**。

### 三种触发方式

```bash
# ① 手动给检索词（可多条）
"D:/Anaconda/python.exe" -m docloom research "OpenHarmony 分布式软总线" "softbus 架构"

# ② 让模型"自己学会搜索"：读第 3 章的提示词 → 自动生成检索词 → 去搜
"D:/Anaconda/python.exe" -m docloom research --chapter 3

# ③ Web UI：运行页的"🔍 联网检索"输入框（手动检索词），
#    或章节详情页的"为本章联网检索素材"按钮（等价于 --chapter 模式）
```

### 它内部做了什么

```
检索词 ──搜索──> 结果列表(标题+链接+摘要)
            │  依次尝试 cn.bing.com → html.duckduckgo.com（或自建 SearXNG）
            ▼
        抓取前 research_fetch_pages 个网页 → 剥掉脚本/导航等只留正文
            ▼
        本地模型逐页提炼：只留与检索词相关的要点（research_digest: true 时）
            ▼
        汇编写入 data/processed/web_<名字>.txt
```

生成的文件和 `parse` 出来的 txt 完全同级——**把文件名填进章节的
`ref_files` 就能用**，截断策略、token 预算等机制照常生效。

### 使用建议

- **先检索后生成**是推荐节奏：`research --chapter N` → 打开 web_*.txt 大致
  扫一眼质量 → 把文件加进该章 ref_files → `run N`。
- 模型没开时也能用：提炼会自动退化为"原文截断"落盘（日志会提示），
  抓资料本身不依赖模型；`--no-digest` 可主动选择这种快速模式。
- 单个网页 403/超时/非文本内容会被自动跳过，不影响其他页面。
- 大陆网络默认 auto（cn.bing 优先）即可；有自建 SearXNG 的话把
  `search_provider` 设为 `searxng` 并填 `searxng_url`，结果质量通常更好。
- 网上抓来的内容**务必人工核对事实**再进正式文档——生成文件的头部
  也写了这条提醒。
