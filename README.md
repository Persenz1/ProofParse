# ProofParse

> Local-first research PDF → Markdown pipeline with a three-layer QC funnel.
> 本地优先的科研论文 PDF → Markdown 解析工作流——不只转换，还知道自己在哪错了、错了能修。

## 为什么

MinerU 这类解析器直接出 Markdown 的工具很多，但解析错了**没人知道**。
ProofParse 在 MinerU pipeline 之上加了一个三层 QC 漏斗，每层只处理上一层筛剩的存疑项，
成本逐层递减、精度逐层递增：

```
PDF
 │
 ├─ Layer 0  MinerU pipeline 解析（本地 GPU）→ Document/Block 中间模型（带页码+bbox）
 │
 ├─ Layer 1  确定性 QC（零模型成本）
 │     · 位置感知文本覆盖率：pypdf 带坐标文字层 ↔ 解析块 bbox 对齐，整句丢失自动补回
 │     · LaTeX 合法性检查（非转义花括号配对等），能修的自动修
 │     · References 确定性截断、Figure/Table 过滤
 │
 ├─ Layer 2  本地公式双识别（PP-FormulaNet+，GPU）
 │     · display 公式全量复核 + math_divergence 段落 inline 复核
 │     · 归一化相似度 ≥0.90 判 PASS，否则标 REVIEW 并生成裁剪图
 │
 └─ Layer 3  多模态终审（只对 needs_review / REVIEW 条目）
       · 裁剪图 + 双候选 + 封闭问题 → 视觉模型裁决 {parser|ocr|custom}
       · 高置信修正自动写回并重建 Markdown；低置信留 still_open 人工
       · 裁决官可插拔：外部 VLM API 或 agent 人工（--export/--from-json）
```

实测（6 篇真实论文：IEEE 双栏、数学密集、33 页长文）：79 条终审项全部裁决，
其中 10 处有效修正自动落入 Markdown，2 篇零修改直接通过。

## 安装

需要 Python 3.12（Windows 上 MinerU 暂不支持 3.13）和 CUDA GPU（CPU 可跑但慢）：

```bash
conda create -n proofparse python=3.12 -y
conda activate proofparse
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
pip install "mineru[pipeline]" six
pip install -e .          # 本仓库
```

## 快速开始

```bash
# 1) 解析（约 60-70 秒/篇；已有输出自动跳过，-f 强制重跑）
proofparse paper.pdf -o output/papers
proofparse ./pdf_folder/ -o output/papers     # 批量：单篇失败不中断

# 2) 第 3 层终审（外部 VLM，OpenAI 兼容接口）
export PROOFPARSE_VLM_BASE_URL="https://api.xiaomimimo.com/v1"
export PROOFPARSE_VLM_API_KEY="sk-..."
export PROOFPARSE_VLM_MODEL="mimo-v2.5"       # 必须是视觉模型
export PROOFPARSE_VLM_EXTRA_BODY='{"thinking":{"type":"disabled"}}'  # MiMo 必须关思考
python -m proofparse.review output/papers -j 4

# 没有 API key？agent/人工裁决官模式：
python -m proofparse.review output/papers --export worklist.json   # 导出待审清单
#   …逐条看 worklist 里 asset 指向的裁剪图，把裁决写进 verdicts.json…
python -m proofparse.review output/papers --from-json verdicts.json

# 3) 看汇总，只有 still_open 需要人工
cat output/papers/review_summary.json
```

## 输出结构

```
output/papers/<name>/
├── <name>.md           # 最终 Markdown（front matter + 标题 + 段落 + $$ 公式）
├── document.json       # 全部块（含被丢弃的），带 page+bbox 可回溯 PDF 坐标
├── document.json.bak   # 终审首次修改前的自动备份
├── qc.json             # QC 明细；终审结果在每条的 final_verdict 字段
├── review_assets/      # 每条存疑项的裁剪图（终审输入）
└── _mineru_raw/        # MinerU 原始输出缓存
output/papers/review_summary.json   # 每篇状态：auto_pass / reviewed / still_open
```

## 作为 Agent Skill 使用

`skill/proofparse/` 是一个完整的 Kimi/Claude Code 风格 skill（SKILL.md + references），
让 agent 用几条 CLI 完成批量提取而不消耗自身上下文去读 PDF：
把它复制到 `~/.config/agents/skills/`（或 Kimi Work 托管 skills 目录），
或直接安装发布页的 `proofparse.skill` 包。

## 配置

全部走环境变量，见 `proofparse/config.py` 与 `skill/proofparse/references/setup.md`：
`PROOFPARSE_PYTHON` / `MINERU_EXE` / `PROOFPARSE_MINERU_DEVICE` /
`PROOFPARSE_VLM_BASE_URL` / `PROOFPARSE_VLM_API_KEY` / `PROOFPARSE_VLM_MODEL` 等。

## 已知限制

- inline 公式的 span bbox 偶发错位（裁剪图拍到邻行），终审可能误判——
  已保守处理（低置信不动正文 + .bak 备份 + agent_override 回滚先例），根治需在 Layer 2 加 bbox 校验
- 文本类警告的两个候选在 qc.json 中是截断前缀；终审时会从 document.json 补全候选 A
- MinerU 3.x content_list 的 bbox 是 1000×1000 归一化坐标；middle.json span 是 PDF 点

## 开发记录

三轮实测数据与错误清单见 `docs/ROUND1_REPORT.md`、第 3 层交接说明见 `docs/HANDOFF.md`。

## License

MIT
