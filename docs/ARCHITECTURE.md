# 架构说明（2026-10-02）

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
| `engines/` | 模型注册表、独立进程 worker、按内容和推理设置缓存；MinerU、PP-DocLayoutV3、三路 HF OCR 适配器 |
| `stages/` | layout → text → recognize → reconcile → assemble，以及 escalate（agent 导出/导入、API 并发） |
| `formula/` | LaTeX 词法、候选比较、结构检查、原生字形约束（计数/上下标/矩阵/编号/边界）、编号保护 |
| `gold/` | arXiv 源码扫描、宏展开、颜色标记编译，产出带位置的公式金标准 |
| `eval/` | 分级打分（strict / layout / loose）、公式识别与行内检测基准 |

## 新模型接入

1. 在 `engines/` 写适配器：`run(job) -> {item_id: output}`，只在 worker 环境中导入模型依赖。
2. 在 `engines/__init__.py` 注册任务类型与模型家族。
3. 在配置中指定该模型的 Python 环境，先跑 `proofparse bench`，再决定是否放进 `pipeline.formula`。

`pipeline.formula` 是常规交叉识别来源；`pipeline.formula_fallback` 按顺序仅处理仍未解决的公式。
切换模型、环境、候选顺序或渲染比例会重跑对应阶段。原始 VLM 响应保留在缓存和候选元数据中，
输出格式处理与模型推理分开，修改格式规则后可直接复用原始响应。

单个行内公式可带 `extra.crop_regions` 和 `extra.crop_baselines`。换行公式只在方括号明确延续、
中间没有正文时合并；各段从源页裁出后按基线横向接齐，不将段间正文放入公式图。
字形校验和任务证据哈希也使用这些分段坐标。行内裁图水平留白 0.25 pt、竖直留白 1.5 pt，
展示公式仍保留 1.5 pt；组合图使用已定位的分段边界。

HF 模型依赖在 worker 内加载。Xiaomi/Ovis 暂归同一个 Qwen3.5 OCR 家族，不能给两张独立确认票。
PaddleX 会间接检查 PyTorch；在 Windows 上必须使用不含 PyTorch 的 Paddle 环境，
仅另起进程但继续继承两套 CUDA 包仍会产生 cuDNN 冲突。

## 尚未完成

- `layout` 任务与 PP-DocLayoutV3 已接入；TeleOCR、MinerU Pro、GLM 尚待实测。
- 独立版面引擎只定位区域；无文字层页面的 OCR 识别调度尚未接入。
- 版面框的程序修正（按文字行、图片、矢量对象吸附）尚未实现。
- 表格结构校验、扫描页 OCR 多路校验尚未实现，表格默认以图片交付。
- 金标准构建仅支持 pdfLaTeX；XeLaTeX/LuaLaTeX 论文会被跳过并记录原因。
- 两个纯数字 `$16$` 在首轮样本中保留为正文；数学外观与正文字体相同的边界仍需更多证据。
- `skill/` 已改为新命令；安装时可选的模型清单（体积、显存）要等模型组合确定后补全。
