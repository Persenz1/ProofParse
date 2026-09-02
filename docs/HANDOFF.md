# 交接提示词：proofparse 第 3 层（多模态终审）

> 用法：新开窗口后，把本文件全文贴给 Agent。工作目录 `D:\Code\PDF`。

---

## 你是谁、要做什么

你是开发 Agent，继续开发 `D:\Code\PDF` 下的 **proofparse** 项目——本地优先的科研
PDF → Markdown 解析工作流（MinerU pipeline 后端 + 三层 QC 漏斗）。
前两层已完成并实测，你的任务是实现**第 3 层：多模态终审**——
读取各论文的 `qc.json`，只对 `needs_review` / `REVIEW` 条目召唤多模态模型裁决，
把裁决结果写回，并支持据此修正 `<name>.md`。

## 环境（已验证可用，不要重装）

- Conda 环境：`D:\DevTools\Conda\envs\litparse\python.exe`（Python 3.12，
  torch 2.14.0+cu126，MinerU 3.4.5，CUDA 可用，RTX 4060 Ti 8GB）
- 运行解析：`cd D:\Code\PDF && D:\DevTools\Conda\envs\litparse\python.exe ingest.py <pdf或目录> -o output\papers [-f]`
  （`-f` 强制重跑；不带则跳过已有输出；`--no-formula-check` 跳过公式双识别）
- 测试样本：`test_pdfs\` 下 6 篇真实论文（IEEE 双栏、数学密集、33 页长文等）
- 已有输出：`output\papers\<name>\{<name>.md, document.json, qc.json, review_assets\, _mineru_raw\}`

## 已完成的部分（不要重做）

1. **解析层**：`proofparse/parsers/mineru_parser.py`，MinerU pipeline 子进程调用，
   统一中间模型 `Document/Block`（含 type/page/bbox），
   References 确定性截断 + Figure/Table 过滤（`normalize/filtering.py`）
2. **QC 第 1 层（确定性）**：位置感知文本覆盖率检查（`normalize/coverage.py`，
   pypdf 带坐标文字层 ↔ MinerU 块 bbox 对齐，整句丢失自动补回）、
   LaTeX 合法性检查（`formula/qc.py`，只统计非转义花括号）、
   元数据从 dropped 块抢救 DOI/year
3. **QC 第 2 层（本地双模型）**：`formula/double_check.py` 用
   **PP-FormulaNet+** 对 display equation 全量复核 + math_divergence 段落
   inline span 复核，`formula/compare.py` 归一化相似度 ≥0.90 判 PASS

## 你的任务：第 3 层多模态终审

新建 `proofparse/review/`，实现（大致）：

1. `review.py`：扫描 `output\papers\*\qc.json`，收集终审清单：
   - `warnings[*]` 中 `status == "needs_review"`（含 `likely_cause`）
   - `formula_check.display[*]` / `formula_check.inline[*]` 中 `verdict == "REVIEW"`
   每条都有 `review_asset`（裁剪图，相对路径）、`page`、`bbox`、
   双候选（`parser` / `formula_ocr` 或 `missing_text` / `parser_text`）
2. 多模态裁决：把裁剪图 + 双候选 + 封闭问题发给多模态模型
   （"两个 LaTeX 候选哪个与图片一致？或给出正确答案"），要求结构化输出
   JSON：`{choice: parser|ocr|custom, corrected_latex, confidence, reason}`
3. 结果写回 `qc.json`（每条加 `final_verdict` 字段），并把确认的正确答案
   应用到 `<name>.md`（公式块可直接替换 content 后重建 markdown；
   文本类警告至少追加标记）。重建用现成的 `normalize/markdown.py` + 
   `document.json` 里的块
4. 生成 `review_summary.json`：每篇论文最终状态（auto_pass / reviewed /
   still_open），供批量运行时只盯着 still_open
5. CLI 集成：`ingest.py --review` 子命令或独立 `python -m proofparse.review output\papers`

## 关键坑（都是实测踩过的，必读）

1. **MinerU 3.x `content_list.json` 的 bbox 是 1000×1000 归一化坐标**；
   `middle.json` 里 span 的 bbox 是 **PDF 点**。换算：
   `x_px = bbox/1000 × page_width_pt × scale`。裁剪用 `proofparse/pdf/render.py`
2. **工具传输层会丢 U+FFFD 字符**（Write/Edit/Bash heredoc 都会）：
   代码里判断替换字符必须写转义 `"\ufffd"`，不能写字面量
3. 花括号配对检查只统计非转义 `{}`（`\left\{ \right.` 是合法分段函数写法）
4. 不要动 `output\papers\` 下已验证的结果除非重跑验证；重跑单篇约 60-70 秒
   （含 MinerU 模型加载），公式双识别模型 PP-FormulaNet+ 权重已在 HF 缓存
5. 环境变量：`PROOFPARSE_FORMULA_MODEL`（unimernet_small/pp_formulanet_plus_m）、
   `PROOFPARSE_MINERU_DEVICE`（cuda/cpu）、`MINERU_EXE`
6. 调用外部多模态 API 前先问用户用哪个服务/key；本地开源 VLM 也可讨论
   （注意 8GB 显存限制，Ministral/Qwen2-VL-2B 量级可行，需实测）

## 验收标准

- 对 6 篇样本跑通终审流程，`qc.json` 每条 needs_review/REVIEW 都有最终裁决
- 抽查 3 条裁决结果与原 PDF 裁剪图人工一致
- 全程不重新解析 PDF（终审只读 qc.json + review_assets + document.json）

## 背景文档

- 任务书原文：`D:\Code\PDF\` 最初附件（如看不到可忽略，报告已覆盖要点）
- `ROUND1_REPORT.md`：三轮开发完整记录（选型依据、实测数据、错误清单）
- `README.md`：安装/使用/QC 漏斗说明
