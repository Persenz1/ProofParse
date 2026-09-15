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
详情见 [复查协议](skill/proofparse/references/qc-format.md)。全页任务检查遗漏和关联，区域任务核对小字、公式及表格。

需要更高清的区域时：

```text
python -m proofparse.read output/papers/paper_name --page 0 --crop 50 100 950 400 --scale 4 --render work/crop.png
```

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
工作文件保留供续跑与核查。导出不会把未完成的复查标记为通过。

## Agent skill 与测试

`skill/proofparse/` 或生成的 `proofparse.skill` 是便携 skill。
包内含安装引导与标准库检测脚本；解析代码需使用仓库或已安装的 Python 包。
技能安装目录遵循各宿主约定，不硬编码。首次安装必须向用户展示选择，不自动下载第三方模型。

- [DeepSeek / 其他 harness 的复测说明](docs/HARNESS_TEST.md)
- [本地 Zotero 样本测试结果](docs/ZOTERO_TEST_RESULTS.md)

本次测试不是四篇论文的逐字验收。未完成的检查保持 still_open，不宣称论文已完全正确。
仍需关注：上游公式编号、复杂表格行列、代码误分类、跨页合并与图片裁剪。相同字符串的行内公式不能唯一定位时不自动替换。
旧版输出建议重新解析；历史修复脚本属于旧协议，不作为新版资料包恢复工具。

## License

MIT
