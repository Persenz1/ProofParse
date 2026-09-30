# 从 PDF 到交付：固定步骤

默认由一个 agent 按顺序执行，不自行启动子代理，也不做额外的复核轮次。
先把路径记下来：PY（解释器）/ INPUT（PDF 或目录）/ OUT（工作目录）/ DELIVERY（交付目录），后面的命令都沿用。

## 1. 解析

```text
proofparse run INPUT -o OUT
```

- 执行一次，等它结束。各阶段按批处理，每个模型只加载一次。
- 中断或失败后运行 `proofparse run --resume OUT`，已完成的阶段不会重做。
- 某篇失败时读 `OUT/<论文>/error.log`，不要反复加 `-f` 盲目重跑。

## 2. 查看状态

```text
proofparse status OUT
```

输出每篇完成了哪些阶段、还有多少未解决项，最后一行 `next:` 就是下一条命令。

## 3. 处理未解决项

**agent 模式：**

```text
proofparse tasks export OUT            # 生成 OUT/tasks.json
```

- instructions 只读一次，然后分批处理任务，每批 5–10 个，逐个打开裁图。
- 答案写进一个 JSON 文件，格式见 tasks-format.md，然后导入：

```text
proofparse tasks import OUT answers.json
```

- 输出里 `rejected` 列出被拒绝的答案及原因。修正后可以只提交这些任务。
- 证据没有变化、判断不了（`open`）的任务，不要反复重答。

**api 模式：** `proofparse tasks api OUT`。结果会缓存；请求失败的任务只报告，不自动重试。

**none 模式：** 跳过这一步，交付时说明哪些没有解决。

## 4. 交付

```text
proofparse export OUT -o DELIVERY
```

- 每篇得到 `<论文名>.md` 和 `images/`，两者一起移动即可正常显示。
- 还有未解决公式时这条命令会拒绝执行。只有用户接受时才加 `--allow-unresolved`，并列出未解决的项。
- OUT 里的工作文件（document.json、原生证据、裁图）留作续跑和核查，不放进交付目录，也不要提前删除。
