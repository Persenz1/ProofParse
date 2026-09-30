# 架构说明（重构骨架，2026-09-30）

## 原则

- 电子版 PDF 的正文以文字层为准，OCR 只兜底；模型输出是候选证据，不是答案。
- 程序负责坐标、归属、裁图、校验与写回；模型负责识别；agent 只回答小而自包含的问题。
- 所有坐标统一为 PDF 点、显示页左上原点。适配器在边界处换算。
- 同一家族的模型（如 PP-FormulaNet M/L）不互为独立证据。
- 自动接受规则写入每个块的 `decision.rule`，由金标准测出每条规则的实际错误率后再定取舍。

## 目录

| 模块 | 作用 |
|---|---|
| `ir.py` | 中间表示：Page / Block / Candidate / Decision；行内公式是子块，父块正文用 `￼` 占位 |
| `preprocess/` | 文字层字形、页面对象、文字层可用性；按点坐标渲染裁图 |
| `engines/` | 模型注册表、独立进程 worker、按内容哈希缓存的 runner；MinerU pipeline 与 MinerU 自带公式模型适配器 |
| `stages/` | layout → text → recognize → reconcile → assemble，以及 escalate（agent 导出/导入、API 并发） |
| `formula/` | LaTeX 词法、候选比较、结构检查、原生字形约束（计数/上下标/矩阵/编号/边界）、编号保护 |
| `gold/` | arXiv 源码扫描、宏展开、颜色标记编译，产出带位置的公式金标准 |
| `eval/` | 分级打分（strict / layout / loose）、公式识别与行内检测基准 |

## 新模型接入

1. 在 `engines/` 写适配器：`run(job) -> {item_id: output}`，只在 worker 环境中导入模型依赖。
2. 在 `engines/__init__.py` 注册任务类型与模型家族。
3. 在配置中指定该模型的 Python 环境，先跑 `proofparse bench`，再决定是否放进 `pipeline.formula`。

## 尚未完成

- 只有 page_parse 类版面引擎（MinerU）接入；独立版面模型（DocLayoutV3、TeleOCR）需要 `layout` 任务的阶段实现。
- 版面框的程序修正（按文字行、图片、矢量对象吸附）尚未实现。
- 表格结构校验、扫描页 OCR 多路校验尚未实现，表格默认以图片交付。
- 金标准构建仅支持 pdfLaTeX；XeLaTeX/LuaLaTeX 论文会被跳过并记录原因。
- `skill/` 安装引导仍是旧流程。
