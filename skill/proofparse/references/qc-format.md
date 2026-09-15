# 复查协议 v2

工作清单为 {schema_version: 2, instructions: 公共规则, items: [...]}。
每项包含 uid、input_hash、kind、page（0-based）、block_id、完整双候选、context、asset、page_asset、source_pdf。
导出路径为当前机器绝对路径；复制资料包后重新导出即可，任务哈希不绑定本机路径。

类型：page_completeness、visual、formula_display、formula_inline、text_warning。
文档及图表 bbox 为可见页面左上原点的 0..1000 坐标；inline 原始 bbox 为 PDF 点，仅供追溯，不可直接当归一化裁剪框。

裁决 JSON 以 uid 为键：

```json
{
  "paper::formula_check/display/0": {
    "input_hash": "从任务复制",
    "choice": "custom",
    "corrected_latex": "\\frac{a}{b}\\tag{2.1}",
    "confidence": 0.95,
    "reason": "原页显示分母 b、公式编号 2.1"
  }
}
```

parser 确认候选 A / 页面完整 / 图像裁剪完整；ocr 使用完整候选 B；custom 提交完整修正；open 无法确定。
表格 parser 或 custom 表示其结构和各行列内容已经视觉核对，随后会显示结构化表格。
input_hash 必填，用于拒绝过期工作清单。不能批量替尚未看图的项目填 parser。

页面 custom 可含 edits: [{block_id, old_content, content}] 和 inserts: [{after_block_id, type, content, bbox}]。
旧内容必须完全匹配，目标及锚点必须位于该页；null 锚点代表页首。
edits 可含 after_block_id 修正页内顺序（null 为页首），也可含 type 纠正文字/代码/公式分类；首页 custom 可含 metadata（title、authors 字符串列表、year 整数、doi），只能依据原页修正。
可插入 paragraph/heading/equation/list/code/figure/table；图表会从原页按 bbox 裁剪，并进入新视觉任务。
visual custom 可提交 crop_bbox: [x1,y1,x2,y2]，在原页重新裁剪后保持待复查；不能把新裁剪自动标记完整。
页面内容修正后需重新看该页，不能自动标记完整。
重复行内公式无法唯一定位时保持 open，不使用首个同名字符串随意替换。

qc.json 包含 warnings、formula_check、page_review、visual_review。
final_verdict 记录 status（resolved/open/error）、application、input_hash、choice、confidence、reason、model。
低置信、失败、过期、未检查都不表示通过。局部修正会使已确认页面需要重新核对。

review_summary.json 的 status：auto_pass（仅无待检查内容）、reviewed、still_open。
新资料包都有逐页检查任务，未完成视觉检查时不会直接 auto_pass。
导入退出码 1 代表仍有未解决项，0 代表全部检查通过；2 为参数/文件配置错误。
API 缓存保存成功响应、usage 和不确定请求状态。调用数量上限不是严格费用封顶。

visual custom 可用 caption 修正完整图注/表题；仅经看图确认的出版商标识可用 ignore_as: publisher_mark 从交付中排除，不能用它隐藏识别失败的科研内容。
