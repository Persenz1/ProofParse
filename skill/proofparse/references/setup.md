# 安装与配置

以下都是用户做出选择之后才执行的示例，不是自动执行清单。

## 主程序

主进程只需要 PyMuPDF、pypdfium2、Pillow。在仓库目录、用户选定的 Python 环境中运行：

```text
<PY> -m pip install -e .
```

## 模型环境

每个模型都在自己配置的 Python 解释器里、以独立进程运行，主进程不加载任何模型代码。
所以不同框架可以放在不同环境里。已知问题：同一个进程里同时加载 Paddle 和 PyTorch 的 CUDA 库，会发生 cuDNN 冲突，两者必须分开。

当前已接入的模型：

| 名称 | 用途 | 需要的环境 |
|---|---|---|
| mineru_pipeline | 版面、阅读顺序，以及第一路公式候选 | MinerU 3.4.5（`mineru[pipeline]`）和 PyTorch |
| unimernet_small / pp_formulanet_plus_m | 公式识别 | 同上，权重由 MinerU 管理 |
| pp_formulanet_plus_l | 公式识别 | Paddle 推理环境，另需导出的 L 权重目录 |

其余候选模型在评测后才接入。模型权重应放在用户统一的模型缓存目录中，可复用的就不要再下载一份；缓存目录不属于每次任务的临时文件。

## 配置文件

查找顺序：环境变量 `PROOFPARSE_CONFIG` → 当前目录的 `proofparse.toml` → 用户目录（Windows 为 `%APPDATA%/proofparse/config.toml`，其他系统为 `~/.config/proofparse/config.toml`）。
完整示例见仓库根目录的 `proofparse.example.toml`。要点如下：

```toml
[pipeline]
layout = "mineru_pipeline"
formula = ["mineru_pipeline", "pp_formulanet_plus_m"]   # 候选来源，按优先顺序

[engines.mineru_pipeline]
python = "<装有 MinerU 的环境的 python>"
device = "auto"          # auto / cuda / cpu

[escalation]
mode = "agent"           # agent / api / none

[escalation.api]
base_url = ""            # OpenAI 兼容接口
model = ""
key_env = "PROOFPARSE_API_KEY"
concurrency = 4
max_requests = 200
```

没有配置文件时，所有模型都用当前解释器运行，升级方式默认为 agent。
写完配置后运行 `proofparse engines`，把各模型实际使用的解释器展示给用户确认。

## 仅阅读已有结果

只装主程序即可。`proofparse status`、`tasks export/import`、`export` 都不需要模型环境。
