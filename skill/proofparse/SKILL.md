---
name: proofparse
description: 批量科研 PDF → Markdown 提取流水线，本地优先（MinerU 解析 + 三层 QC 漏斗：文本覆盖率确定性检查 → 本地公式双模型复核 → 多模态终审），每条存疑处附裁剪图供终审。当用户要求批量提取/转换论文 PDF 为 Markdown、校验解析质量、处理 qc.json / review_summary.json / still_open 条目，或要求"节省 agent 额度地读论文"时使用。不要自己整页读 PDF 或手写 OCR——调用本 skill 的 CLI；只有 still_open 条目才需要 agent 亲眼看裁剪图。
---

# proofparse：批量论文 PDF → Markdown（三层 QC）

项目根：本仓库克隆目录（下文记作 `<repo>`）。Python：按 README 装好依赖的
解释器（conda 环境或 `pip install -e .` 后的 `python`；亦可用
`PROOFPARSE_PYTHON` 指定）。Git Bash 中路径一律用正斜杠。

## 额度节省协议（核心原则）

- 永不整读 PDF、永不手写 OCR/公式识别——全部交给 CLI 子进程
- 解析、第 1/2 层 QC 全自动零成本；第 3 层终审用便宜的外部 VLM API（约百次调用/批）
- agent 只看两个文件：`review_summary.json`（每篇状态）和 still_open 条目的裁剪图
- 终审全程不重解析 PDF（只读写 qc.json / document.json / md）

## 三步流程

```bash
cd <repo>
PY=${PROOFPARSE_PYTHON:-python}

# 1) 解析 + 确定性 QC + 公式双识别（GPU，约 60-70 秒/篇；已有输出自动跳过，-f 强制）
$PY ingest.py <pdf文件或目录> -o output/papers

# 2a) 终审：外部多模态 API（推荐，需先配置，见 references/setup.md）
$PY -m proofparse.review output/papers -j 4

# 2b) 终审：agent 裁决官模式（无 API key 时；先导出清单，逐条看 asset 图，
#     把裁决写成 {"uid": {"choice": "parser|ocr|custom", "corrected_latex": ...,
#     "confidence": 0-1, "reason": "..."}} JSON，再导回）
$PY -m proofparse.review output/papers --export worklist.json
$PY -m proofparse.review output/papers --from-json verdicts.json

# 3) 读汇总，只处理 still_open
cat output/papers/review_summary.json
```

裁决语义：`parser`=解析器候选正确；`ocr`=另一候选正确；`custom`=两者皆错，
须给 `corrected_latex`。高置信（≥0.7）的非 parser 裁决会自动改 document.json
并重建该篇 md；低置信保持 still_open 不动正文。

## 输出结构（每篇 `output/papers/<name>/`）

- `<name>.md` — 最终 Markdown（front matter + 标题层级 + 段落 + `$$` 公式）
- `qc.json` — 警告与公式复核明细；终审结果在每条目的 `final_verdict`
- `review_summary.json`（在 output/papers 根）— 状态：`auto_pass` /
  `reviewed` / `still_open`
- `review_assets/*.png` — 每条存疑的裁剪图（终审输入）
- `document.json`（含被丢弃块，块带 page+bbox，可回溯 PDF 坐标；
  首次终审修改前自动备份 `document.json.bak`）
- `_mineru_raw/` — MinerU 原始输出缓存（可据此无 GPU 复原 document.json）

## 关键坑（都实测踩过）

- MinerU content_list 的 bbox 是 1000×1000 归一化坐标；middle.json span 是 PDF 点
- MiMo 看图必须用 `mimo-v2.5`（`mimo-v2.5-pro` 纯文本），且要关思考模式：
  `PROOFPARSE_VLM_EXTRA_BODY='{"thinking":{"type":"disabled"}}'`
- 代码里判断替换字符写转义 `"\ufffd"`，不写字面量（工具传输会丢该字符）
- inline 公式 span bbox 偶发错位（裁到邻行）：VLM 判错时回滚
  （`document.json.bak` + qc.json 里 `agent_override` 先例）
- 不要重跑 ingest 覆盖已终审结果；终审前想复原用 `restore_pristine.py`

## 参考文档

- VLM 配置、性能数据、环境变量全表：references/setup.md
- qc.json / final_verdict / review_summary 字段定义：references/qc-format.md
