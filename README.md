# ProofParse

Local-first PDF extraction and visual review for any agent/harness.

把论文一次性转换为可按需阅读的资料包：完整正文、公式、图表、参考文献和附录。
本地 MinerU 解析；从源页检查遗漏；当前多模态 agent 或显式授权的兼容 API 复查。
独立 CLI/JSON 协议，不依赖 Codex 或 DeepSeek 专有工具。

## 安装前先选择

先用已有 Python 运行只读检测：

```text
python skill/proofparse/scripts/setup_probe.py
```

检测不安装或下载任何东西。然后选择：复用已有环境、新建 GPU 环境、新建 CPU 环境，或仅阅读/复查已有结果。
安装者必须展示需要安装的依赖、第三方模型、缓存位置和已知下载影响，用户选择后再安装。
具体说明见 [安装与模型选择](skill/proofparse/references/setup.md)。

本次验证环境：Python 3.12.14、MinerU 3.4.5、Windows、RTX 4060 Ti 8GB。
用户选定环境后，在仓库中 `python -m pip install -e .`。
完整解析额外需要 `mineru[pipeline]==3.4.5`、PyTorch 和已授权的本地模型权重。
仅阅读/复查不要求安装 MinerU 或下载公式模型。

## 使用

以下 python 指用户选择的解释器，不一定是系统默认 Python。

```text
python -m proofparse.cli papers/ -o output/papers
python -m proofparse.read output/papers/paper_name
python -m proofparse.read output/papers/paper_name --page 0
python -m proofparse.review output/papers
python -m proofparse.read output/papers/review_worklist.json --kind visual --limit 3
```

设置 `PROOFPARSE_WORK_DIR` 指定本次临时目录；未设置则保留原始缓存到输出目录。
模型权重缓存不属于每次任务的临时文件。相同 PDF 已有完整产物可跳过；同名不同内容会报错，避免误用旧结果。

### 多模态复查

导出是准备工作，不是视觉验证。宿主打开任务里的 asset/page_asset，按公共 instructions 写裁决：

```text
python -m proofparse.review output/papers --from-json verdicts.json
```

协议要求任务 input_hash，拒绝陈旧裁决。支持候选选择、完整修正、页内插入、重排和重新裁剪。
工作清单 v3 使用持久 uid 标识问题，block_id 标识对象，input_hash 标识当前证据；排序、换处理者和重裁不会改变 uid。
首次读取旧工作目录会补充问题 ID，并用已保存的两路候选更新比较结果，不重跑 OCR。升级后需重新导出工作清单；旧裁决不能直接套用。
公式任务提供主体的写法/排版/内容差异和独立编号差异，保留两路完整原文。差异位置是规范化 token 下标，长差异仅显示预览。
简单公式修正会保留遗漏的原编号；主动改编号需提交 `number_correction: {old: [原 tag], new: [新 tag]}`。
段落修正默认保留行内数学；需要改公式或修复定界符时，提交 `math_edits: [{old: 原数学片段, new: 带定界符的新数学片段}]`，每个 old 必须唯一匹配。
补段会检查同页和邻页的已有文字，避免重复写入跨页合并的内容。
详情见 [复查协议](skill/proofparse/references/qc-format.md)。全页任务检查遗漏和关联，区域任务核对小字、公式及表格。

需要更高清的区域时：

```text
python -m proofparse.read output/papers/paper_name --page 0 --crop 50 100 950 400 --scale 4 --render work/crop.png
```

### 原生字符约束（可选）

安装了 `native` extra（PyMuPDF）时，导出/收集复查任务会读取源 PDF 的字符、字体资源、字形 ID 和坐标，无需重跑 OCR。默认清单只带字体、编号和数学/正文边界约束摘要；完整字符几何及候选对齐位于各论文工作目录的 `native_evidence.json`，按 `details_key` 读取。没有 PyMuPDF 或源 PDF 时明确显示不可用，沿用原复查流程。

重复符号保留歧义，编号按位置关联；这些约束不会自动确认或改写 LaTeX。两路 OCR 一致但原生证据存在冲突时，仍生成待审任务及必要裁图。新增证据参与 `input_hash`，受影响的旧裁决需要刷新。

字体名不自动解释为花体。宿主看过原图并确认具体字形后，可登记文档内映射：

```text
python -m proofparse.review.native output/papers/paper_name --confirm-glyph PAGE SPAN CHAR --text K --styles calligraphic
```

`PAGE` 为从 0 起的页码，`SPAN CHAR` 是字符证据的 `source_index`。字符纠码可省略 `--styles`。映射保存为 `native_glyphs.json`，绑定源 PDF、字体资源和字形；不会跨论文套用，也不替换原始证据中的字符。登记后重新导出工作清单。原生证据无法独立恢复所有分式、矩阵或损坏编码，完整公式仍按现有视觉复查与修正协议处理。

### 可选独立 API

配置 `PROOFPARSE_REVIEW_API_KEY` 后，以下命令明确授权发送待审图片和文本：

```text
python -m proofparse.review output/papers --api --api-url <base_url> --api-model <vision_model> --max-requests 20 --max-output-tokens 4096
```

保存响应供续跑；结果不明时不盲目重试。请求/输出上限不等于严格货币费用封顶。
本次只模拟验证 API 缓存逻辑，未调用真实供应商接口。

## 资料包

```text
paper_name/
  paper_name.md       # 阅读视图；图像链接按需打开
  document.json       # 权威内容、稳定块 ID、原始字段
  source.pdf          # 原始输入，支持复查与重新裁剪
  assets/             # 完整图表和无法结构化的区域
  qc.json             # 本地问题、逐页/图表复查状态
  review_assets/      # 原页与问题裁剪图
```

Markdown 不删除参考文献和附录。未验证的表格默认显示原图，确认后生成 Markdown 或有限 HTML，原图仍保留。
公式相似度仅用于排序；不删除上下标分组、矩阵行列、字体差异后判定正确。

## 最终交付

上面的目录是解析与复查工作目录。用户最终只需接收 Markdown 和图片：

```text
python -m proofparse.export output/papers -o delivery
```

每篇得到 `<论文名>.md` 与 `images/`，Markdown 用相对路径直接嵌入对应图片。没有 JSON、PDF 或日志；整个论文目录可一起移动。
工作文件保留供续跑与核查。导出不会把未完成的复查标记为通过。检测到公式 LaTeX 结构损坏时，导出会停止并给出 block_id，不用公式截图替代转录；结构检查通过也不代表公式已被视觉核实。

## Agent skill 与测试

`skill/proofparse/` 或生成的 `proofparse.skill` 是便携 skill。
包内含安装引导与标准库检测脚本；解析代码需使用仓库或已安装的 Python 包。
技能安装目录遵循各宿主约定，不硬编码。首次安装必须向用户展示选择，不自动下载第三方模型。

- [DeepSeek / 其他 harness 的复测说明](docs/HARNESS_TEST.md)
- [本地 Zotero 样本测试结果](docs/ZOTERO_TEST_RESULTS.md)
- [公式识别开发与测试问题报告（2026-09-30）](docs/FORMULA_EVALUATION_2026-09-30.md)

本次测试不是四篇论文的逐字验收。未完成的检查保持 still_open，不宣称论文已完全正确。
仍需关注：上游公式编号、复杂表格行列、代码误分类、跨页合并与图片裁剪。相同字符串的行内公式不能唯一定位时不自动替换。
旧版输出建议重新解析；历史修复脚本属于旧协议，不作为新版资料包恢复工具。

## License

MIT
