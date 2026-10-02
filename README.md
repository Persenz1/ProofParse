# ProofParse

本地优先的科研 PDF → Markdown 工具。正文取自 PDF 文字层；版面、公式、表格模型可替换，
各自在独立进程和环境中运行；公式由多路独立证据交叉校验，本地判断不了的交给 agent 或 API。

> 当前是重构中的开发版（0.3.0.dev0）。首轮已实测 PP-DocLayoutV3、Xiaomi-OCR-0、
> PaddleOCR-VL-1.6 和 OvisOCR2，见 [适配测试结果](docs/MODEL_ADAPTATION_2026-10-02.md)。
> 后续范围见 [开发计划](docs/DEVELOPMENT_PLAN.md) 和 [架构说明](docs/ARCHITECTURE.md)。
> 重构前的测试报告见 [docs/history/](docs/history/)。

## 流程

```text
preprocess  PyMuPDF 读文字层、字体、字形坐标、图片与矢量对象；判断每页是否需要 OCR
layout      版面模型给出区域和阅读顺序（MinerU pipeline / PP-DocLayoutV3）
text        按字形把正文归入区域；数学字体字形组成行内公式；正文用占位符引用公式
recognize   从源页统一裁图，主模型分别识别；补充模型只处理未解决项
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

首轮电子版 PDF 的实验组合配置见 [proofparse.vlm.example.toml](proofparse.vlm.example.toml)：
V3 版面、M + PaddleOCR-VL 交叉识别、Xiaomi 定向补识别。新 VLM 使用独立
Transformers 5 环境；V3 的 Paddle 环境必须不含 PyTorch。此配置尚未覆盖扫描页和整篇论文。

```text
python -m proofparse --config proofparse.vlm.example.toml run paper.pdf -o out
```

## 金标准与评测

```text
proofparse gold build output/arxiv_gold            # arXiv 源码编译两遍，得到公式位置与 LaTeX
proofparse bench formula output/arxiv_gold -e unimernet_small,pp_formulanet_plus_m
proofparse bench inline output/arxiv_gold          # 行内公式检测的字形级精确率/召回率
```

`bench formula` 除各模型准确率外，还统计每对模型"一致但都错"的次数，这决定哪些组合能互相校验。
词法匹配刻意保守；`--render-compare` 可增加规范 TeX 字形与几何等价比较，需要已有的 `pdflatex`。

## 候选模型下载

Windows 在可访问 Hugging Face 的网络下运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\download_models.ps1
# 只下载第一批六个候选（不含 GLM）
powershell -ExecutionPolicy Bypass -File .\scripts\download_models.ps1 -Group first-batch
```

默认复用 `D:\DevTools\Conda\envs\litparse\python.exe`，将七个候选（约 13.4 GB）
放进 `D:\DevTools\Models\huggingface\hub`，使用固定版本和断点续传。
`-List` 只查看清单；`-Models 'xiaomi,ovis'` 只下载指定模型；
`-CacheDir` 和 `-PythonExe` 可改路径。下载结束会显示各模型的实际快照目录。
四个首轮模型已有适配器与本机实验环境；TeleOCR、MinerU Pro 和 GLM 仍待实测接入。
下载脚本不加载模型。

其他环境可用 `python scripts/download_models.py --help` 查看参数，
并用 `--cache-dir` 指定本机目录。仅需要 `huggingface_hub` 下载依赖。

## 测试

```text
python -m pytest tests
```

## License

MIT
