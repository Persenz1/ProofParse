# qc.json 与终审结果格式

## qc.json 顶层

```json
{
  "parser": {...}, "filter_stats": {...},
  "n_display_equations": 0, "n_inline_math_spans": 0,
  "n_auto_fixed": 0,            // 第 1 层自动修复数（LaTeX 修括号、覆盖率补句）
  "fixes": [...],
  "warnings": [...],            // 文本覆盖率警告
  "summary": {"n_needs_review": 0, ...},
  "formula_check": {            // 第 2 层双识别结果
    "model": "pp_formulanet_plus_m",
    "display": [...], "inline": [...],
    "n_display_checked": 0, "n_display_review": 0,
    "n_inline_checked": 0, "n_inline_review": 0
  }
}
```

## warnings[*]（文本类）

- `status`: `auto_fixed` | `needs_review`
- `likely_cause`: `math_divergence`（公式导致歧义，含 `formula_spans` 明细）|
  `possible_text_loss`（疑似丢字）
- `missing_text`（PDF 文字层候选）/ `parser_text`（解析器候选，均可能截断）
- `page` / `bbox`（1000 归一化）/ `review_asset`（裁剪图相对路径）

## formula_check.display[*] / inline[*]

- `verdict`: `PASS` | `REVIEW`（归一化相似度 <0.90）
- `parser` / `formula_ocr` 双候选；`similarity`
- display 有 `block_index`（定位 document.json 块）；inline 只有 `page`+`bbox`
  （inline 的 bbox 单位是 **PDF 点**，display 是 1000 归一化）

## final_verdict（第 3 层终审写回，每条被审条目上）

```json
{
  "reviewed_at": "ISO 时间", "layer": "multimodal",
  "status": "resolved | error",
  "choice": "parser | ocr | custom",
  "corrected_latex": null,
  "confidence": 0.95, "reason": "...", "model": "mimo-v2.5",
  "agent_override": true,          // 可选：agent 人工推翻 VLM 时
  "previous_verdict": {...}        // 可选：被推翻的原裁决
}
```

- `choice=parser`：解析器正确，md 不动
- `choice=ocr/custom` 且 confidence ≥0.7：已自动应用到 document.json 并重建 md
- confidence <0.7 或 `status=error`：md 不动，论文进入 still_open

## review_summary.json（output 根目录）

```json
{"<paper>": {"status": "auto_pass | reviewed | still_open",
             "n_reviewed": 0, "n_applied": 0, "n_confirmed": 0,
             "n_skipped": 0, "seconds": 0}}
```

批量运行只盯 `still_open`：打开该篇目录，按 qc.json 里无有效
`final_verdict` 的条目找 `review_asset` 裁剪图人工裁决，
再用 `--from-json` 导回。
