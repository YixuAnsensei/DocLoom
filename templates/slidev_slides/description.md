Slidev 幻灯片模板 — 模板填空式生成技术分享 slides（双栏/点击动画/代码页，低温度）

## 使用方法

1. `docloom new my_talk --template slidev_slides`
2. 把你的分享素材（笔记/文档/论文）丢进 `data/raw/`，跑 `docloom parse`
3. 把 processed 里生成的 txt 文件名填进各章 `ref_files`（模板里占位写的是 `notes.txt`，
   可以直接把你的主素材改名为 notes.txt 最省事）
4. `docloom review` 预检 → `docloom run`
5. 演示：
   ```bash
   npm i -g @slidev/cli
   slidev output/Final_Slidev.md          # 浏览器实时演示
   slidev export output/Final_Slidev.md   # 导出 PDF
   ```

## 模板说明

- 每章模板已内置 Slidev 语法：`---` 分页、`layout: two-cols` 双栏 + `::right::` 分栏符、
  `<v-clicks>` 逐条显示动画、代码页。模型只做【】填空，不会动这些结构。
- 章节标题（engine 注入的 `## 标题`）就是该章第一页的页标题，改章节名 = 改页标题。
- 想换主题：`slidev --theme seriph output/Final_Slidev.md`（生成的文件不含全局
  frontmatter，主题用命令行参数指定最稳）。
- 按你的分享内容增删章节：直接改 prompts.json 或在网页章节页操作，
  每章模板记得以单独一行 `---` 结尾（最后一章除外），这样章与章的分页才正确。

## 代码块规范

- 所有代码围栏必须带语言标识，例如 ` ```python `、` ```typescript `、` ```json ` 或 ` ```bash `，以便 Slidev 高亮。
- 每页代码最多 10 行；长逻辑拆页，并只保留讲解当前观点所需的最小片段。
- 资料有真实代码时保持标识符与语义；没有代码时写贴近方案的伪代码，并在页内说明是伪代码。
