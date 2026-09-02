# proofparse 环境与配置

## 运行环境

- Conda 环境：`D:\DevTools\Conda\envs\litparse\python.exe`（Python 3.12，
  torch + CUDA，MinerU pipeline，PP-FormulaNet+ 公式双识别）
- GPU：RTX 4060 Ti 8GB 实测可行；`PROOFPARSE_MINERU_DEVICE=cpu` 可退化为 CPU（慢）
- 解析吞吐：约 60-70 秒/篇（含模型加载；批处理只加载一次）
- 公式双识别可用 `--no-formula-check` 跳过（快约 30%，但 REVIEW 清单会变粗）

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `PROOFPARSE_PYTHON` | `D:\DevTools\Conda\envs\litparse\python.exe` | 专用解释器 |
| `MINERU_EXE` | 同上 Scripts/mineru.exe | MinerU CLI 路径 |
| `PROOFPARSE_MINERU_DEVICE` | `cuda` | `cuda` / `cpu` |
| `PROOFPARSE_VLM_BASE_URL` | — | 终审 VLM（OpenAI 兼容） |
| `PROOFPARSE_VLM_API_KEY` | — | 终审 key，只走环境变量，勿写入文件 |
| `PROOFPARSE_VLM_MODEL` | — | 必须是视觉模型 |
| `PROOFPARSE_VLM_EXTRA_BODY` | `{}` | 厂商私有参数（JSON 字符串） |
| `PROOFPARSE_VLM_TIMEOUT` | 120 | 秒 |
| `PROOFPARSE_VLM_MAX_TOKENS` | 4096 | 思考模式会吃掉额度，务必关 |

## 终审 VLM：MiMo 配置（实测可行）

```bash
export PROOFPARSE_VLM_BASE_URL="https://api.xiaomimimo.com/v1"
export PROOFPARSE_VLM_API_KEY="sk-..."        # 按量付费 key
export PROOFPARSE_VLM_MODEL="mimo-v2.5"      # 注意：mimo-v2.5-pro 是纯文本，不能看图
export PROOFPARSE_VLM_EXTRA_BODY='{"thinking":{"type":"disabled"}}'
```

成本量级：79 条约 ¥0.1-0.5。任何 OpenAI 兼容视觉接口都能用
（DashScope qwen-vl-max、GPT-4o 等），只要换这三个变量。

## 复原与回滚

- 终审首次改动前自动备份 `document.json` → `document.json.bak`
- 想整体复原（如裁剪图生成逻辑升级后）：项目根 `restore_pristine.py <paper_dir>...`
  从 `_mineru_raw` 缓存重建 document.json + md，保留 qc.json 裁决记录，
  并用大边距重生成复核图（无 GPU、约 2 秒/篇）
