# 未解决项：任务与答案格式

## tasks.json

```json
{
  "schema": 1,
  "instructions": "公共规则，只读一次",
  "answer_example": {...},
  "tasks": [
    {
      "task_id": "论文名/p003b012",
      "input_hash": "当前证据的哈希",
      "kind": "display_math | inline_math",
      "page": 3,
      "image": "公式裁图的绝对路径",
      "page_image": "整页图的绝对路径",
      "bbox_pt": [x0, y0, x1, y1],
      "context_text": "行内公式所在段落，⟦THIS⟧ 标出本公式，⟦math⟧ 是其他公式",
      "candidates": [{"engine": "模型名", "latex": "..."}],
      "status": "conflict | unverified | failed",
      "differences": [...],
      "source_checks": {...}
    }
  ]
}
```

- 页码从 0 开始；坐标单位是 PDF 点，原点在显示页面的左上角。
- `differences`：候选之间在哪里不一致，下标指规范化后的 token，不是原始字符位置。
- `source_checks`：各候选与 PDF 文字层的冲突，例如字形数量、字体、上下标、矩阵行数、编号、正文混入。这些是线索，不是结论。

## 答案

一个 JSON 对象，键为 task_id：

```json
{
  "论文名/p003b012": {"input_hash": "从任务原样复制", "choice": "pp_formulanet_plus_m"},
  "论文名/p004b002.m01": {"input_hash": "…", "choice": "custom", "latex": "\\mathcal{K}_{t}^{\\top} x"},
  "论文名/p005b007": {"input_hash": "…", "choice": "open"}
}
```

- `choice` 取值：某个候选的 engine 名 / `custom`（必须同时给出完整的 `latex`）/ `open`（判断不了）。
- LaTeX 不要带 `$` 或 `\[ \]` 定界符；在 JSON 里反斜杠要写成 `\\`。
- 公式编号只能写成 `\tag{...}`。答案漏掉原有编号时，程序会自动保留；确实要改编号时，另加 `"number_correction": {"old": [原 tag], "new": [新 tag]}`。
- 只提交实际看过图的任务。

## 拒绝原因

| 原因 | 含义 |
|---|---|
| stale_input_hash | 导出任务之后证据变了，需要重新导出再作答 |
| unknown_candidate | choice 不是该任务里的任何候选 |
| custom_without_latex | 选了 custom 却没给 latex |
| math_delimiters_in_latex | latex 里带了定界符 |
| invalid_latex:… | 括号、\left/\right、环境不配对等结构错误 |
| protected_equation_number | 改动了编号，但没有给出 number_correction |
| empty_equation_body / nested_math_delimiters | 公式主体为空，或嵌套了定界符 |
| left_open | 答了 open，仍然保留为未解决 |
