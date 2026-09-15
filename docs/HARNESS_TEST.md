# 跨 agent/harness 复测

## 本机已经准备好

- 独立测试副本：`output/deepseek_test/`
- 固定 7 个任务：`output/deepseek_test/harness_cases.json`
- 未裁决基线：`output/harness_baseline/`
- 原始输入：`test_pdfs/zotero/`

四篇 Zotero 论文共 69 页：Instability of a penetrating blade（15）、Bioinspired microrobots（12）、Simultaneous localization and mapping: Part I（10）、Robotics Software: Past, Present, and Future（32）。
任务覆盖图像裁剪、公式、表格及整页完整性。先完成相同 7 个任务，再决定是否执行全部 239 个任务。
不要在独立裁决前阅读 Codex 的结果文件或 ZOTERO_TEST_RESULTS.md，以免影响比较。

## 给 DeepSeek 的任务

在 ProofParse 仓库根运行。先读取 skill/proofparse/SKILL.md；首次安装按其引导展示选项，不自动下载模型。
复查已有结果只需要核心依赖和宿主看图能力，不需要重跑 MinerU。
本机已经可用的解释器为 D:/DevTools/Conda/envs/litparse/python.exe；这不是其他机器的默认路径。

1. 阅读 harness_cases.json 的 instructions 一次。
2. 用下面的命令分批读取任务，实际打开 asset，必要时查看 page_asset 或重新渲染区域。
3. 将实际看过的 7 个任务写入自己的 verdicts.json；保留 uid/input_hash。
4. 导入到 deepseek_test，报告更改、确认、未解决和工具适配问题。
5. 不要求全部判通过；如宿主不能看图，明确报告能力缺失。

```text
<PY> -m proofparse.read output/deepseek_test/harness_cases.json --offset 0 --limit 2
<PY> -m proofparse.review output/deepseek_test --from-json output/deepseek_test/verdicts.json
```

导入后仍有其他未处理页，退出码 1 和 still_open 是预期，不代表命令失败。
避免改动 output/harness_baseline；Codex 的样本结果位于 output/zotero_test，不要覆盖。
不要把相同的裁决重复导入 --force。修改会使相关页重新需要复查。

## 另一个 harness / 另一台机器

只复制代码与完整 baseline 目录即可，不需要原开发机的 Zotero 或 MinerU 缓存。
每个 harness 创建独立副本，重新导出绝对路径：

```text
<PY> scripts/prepare_harness_test.py <baseline目录> <新的输出目录>
```

目标目录必须不存在；脚本不删除旧结果。input_hash 不依赖机器路径，因此可比较同一输入证据。
查看图像的工具名称由宿主决定；不能用“读到文件路径”代替实际看到图片。

比较时区分：模型判断差异、图片分辨率/工具能力差异、协议理解差异和代码执行失败。
记录宿主和模型版本，以及工具能提供的真实用量；无法取得 token 统计时写未知，不估算成实测。
