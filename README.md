# ProofParse

本地优先的科研 PDF → Markdown 工具。正文取自 PDF 文字层；版面、公式、表格模型可替换，
各自在独立进程和环境中运行；公式由多路独立证据交叉校验，本地判断不了的交给 agent 或 API。

> 当前是重构中的测试前骨架（0.3.0.dev0）。候选模型尚未接入与实测，
> 见 [开发计划](docs/DEVELOPMENT_PLAN.md)、[模型选型计划](docs/MODEL_SELECTION_PLAN_2026-09-30.md) 和 [架构说明](docs/ARCHITECTURE.md)。
> 重构前的测试报告见 [docs/history/](docs/history/)。

## 流程

```text
preprocess  PyMuPDF 读文字层、字体、字形坐标、图片与矢量对象；判断每页是否需要 OCR
layout      版面模型给出区域和阅读顺序（当前：MinerU pipeline）
text        按字形把正文归入区域；数学字体字形组成行内公式；正文用占位符引用公式
recognize   从源页统一裁图，各公式模型分别识别
reconcile   两个以上独立模型家族一致、LaTeX 结构合法、与原生字形无冲突才自动接受
assemble    生成工作视图 Markdown；未解决项在交付前必须解决
```

## 使用

```text
proofparse run papers/ -o out          # 可中断，重跑即续跑
proofparse status out                  # 进度、待解决数量、下一条命令
proofparse tasks export out            # 待解决项 -> out/tasks.json，由当前 agent 作答
proofparse tasks import out answers.json
proofparse tasks api out               # 或用配置的 API 并发作答
proofparse export out -o delivery      # 每篇 <名>.md + images/
```

配置见 [proofparse.example.toml](proofparse.example.toml)：每个模型用哪个 Python 环境、
候选顺序、升级方式（agent / api / none）。

## 金标准与评测

```text
proofparse gold build output/arxiv_gold            # arXiv 源码编译两遍，得到公式位置与 LaTeX
proofparse bench formula output/arxiv_gold -e unimernet_small,pp_formulanet_plus_m
proofparse bench inline output/arxiv_gold          # 行内公式检测的字形级精确率/召回率
```

`bench formula` 除各模型准确率外，还统计每对模型"一致但都错"的次数，这决定哪些组合能互相校验。

## 测试

```text
python -m pytest tests
```

## License

MIT
