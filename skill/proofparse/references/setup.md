# 安装与模型选择

先执行 SKILL.md 中的只读检测，并展示安装选项。以下命令是用户选择后的示例，不是自动执行清单。

## 复用环境

在已有 Python 环境、仓库目录中：

```text
<PY> -m pip install -e .
```

仅当还缺少解析器且用户同意下载：

```text
<PY> -m pip install "mineru[pipeline]==3.4.5" six
```

本次实际测试版本：Windows / Python 3.12.14 / MinerU 3.4.5 / pypdfium2 5.10.1。
这是已测组合，不表示其他平台组合已验证。不同 MinerU 版本先核对输出字段再升级。

## 新环境

建议独立 Python 3.12 环境。环境名和安装位置由用户选择，不修改或删除现有环境。
GPU 用户先确认驱动兼容的 PyTorch 构建；CPU 用户选择 CPU 构建。
设备默认 auto：以当前 Python 的 torch.cuda.is_available() 为准，有 CUDA 则用 cuda，否则用 cpu。
可用 PROOFPARSE_MINERU_DEVICE=cpu/cuda 手动指定，不自动覆盖显式选择。
安装完成后再次运行检测脚本，向用户展示解释器、实际选择设备和模型缓存位置。
不要把开发机 CUDA 版本当作所有用户默认值。

MinerU 会使用版面、OCR、公式、表格等模型。首次运行可能自动下载权重。
第二公式识别使用 PP-FormulaNet+；需明确授权下载和缓存位置。
MINERU_FORMULA_CH_SUPPORT 会影响第一路公式模型选择，不能默认双路必然是不同模型。

模型来源、缓存目录和下载量应在安装前展示；未知下载量明确写待确认。
已有权重尽量复用，不默认再下载一份。缓存目录不是每次任务结束应删除的临时目录。

## 仅阅读/复查

安装核心包即可，不安装 MinerU、PyTorch 或第二公式模型。需要已有 paper 资料包。
从源代码目录也可直接用 Python -m 命令运行，但渲染需要 pypdfium2 和 Pillow。
纯文本宿主可导出任务；视觉校验需要宿主本身支持图片或用户授权独立 API。

## 环境变量

| 变量 | 用途 |
|---|---|
| PROOFPARSE_PYTHON | 选择解析器所在 Python；CLI 本身也应由该解释器启动 |
| MINERU_EXE | 明确指定 MinerU CLI 路径 |
| PROOFPARSE_MINERU_DEVICE | auto（默认）/ cuda / cpu |
| PROOFPARSE_FORMULA_MODEL | pp_formulanet_plus_m / unimernet_small |
| PROOFPARSE_WORK_DIR | 本次临时模型输出目录；未设置时原始缓存留在论文输出目录 |
| MINERU_TOOLS_CONFIG_JSON | 已有 MinerU 配置路径 |
| HF_HOME / MODELSCOPE_CACHE | 模型缓存根；需在运行前选择并核对上游配置 |
| PROOFPARSE_REVIEW_API_KEY | 可选 API 密钥 |

--no-formula-check 可以跳过第二公式模型，但状态会明确保留 not_run，不能宣称完整检查已通过。
source.pdf、assets 和 review_assets 都是资料包功能所需文件；清理临时目录前确认交付不引用其中路径。
